"""Sync spam list din IRIS Gateway (admin_cts.email_whitelist) → MG spam blacklist.

Flux:
  1. GET {IRIS_API_URL}/mailguard/spam-whitelist  (Header: X-Mailguard-Key)
     — IRIS expune whitelist-ul CTS fără credențiale DB separate
  2. Fiecare email din răspuns → sender_lists.add_entry(blacklist, tip=spam)
  3. Salvare stare sync în settings['cts_spam_sync_state']

Același pattern ca iris_sync.py / sync_clients_from_iris().
IRIS_MAILGUARD_API_KEY trebuie setat în .env (deja prezent pentru sync clienți).
"""
import json
import logging
import os

import httpx
from datetime import datetime, timezone
from sqlalchemy import text

from app.config import get_settings
from app.database import SessionLocal
from app.services import sender_lists

logger = logging.getLogger("mailguard.cts_spam_sync")

_STATE_KEY = "cts_spam_sync_state"

# Endpoint IRIS pentru whitelist spam CTS — de confirmat cu Razvan/admin IRIS
_IRIS_SPAM_ENDPOINT = os.getenv("IRIS_SPAM_WHITELIST_PATH", "/cargo360/spam-whitelist")


def is_configured() -> bool:
    mg_key = os.getenv("IRIS_MAILGUARD_API_KEY", "").strip()
    iris_url = get_settings().iris_api_url.strip()
    return bool(mg_key and iris_url)


def get_sync_state(db) -> dict:
    row = db.execute(text("SELECT value FROM settings WHERE key=:k"), {"k": _STATE_KEY}).fetchone()
    return (row[0] if row and row[0] else {}) or {}


def _save_state(db, state: dict):
    db.execute(text(
        "INSERT INTO settings(key, value, description, updated_by, updated_at) "
        "VALUES(:k, CAST(:v AS jsonb), "
        "'Stare sync spam IRIS → Cargo360 (admin_cts.email_whitelist via IRIS API)', "
        "'cts_spam_sync', NOW()) "
        "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, "
        "updated_by=EXCLUDED.updated_by, updated_at=NOW()"
    ), {"k": _STATE_KEY, "v": json.dumps(state)})
    db.commit()


def run_sync(triggered_by: str = "auto") -> dict:
    """Preia spam whitelist din IRIS API și sincronizează în MG spam blacklist.
    Returnează {ok, added, skipped, errors, last_sync_at} sau {ok:False, error}.
    """
    if not is_configured():
        return {"ok": False, "error": "IRIS_MAILGUARD_API_KEY lipsă în .env"}

    mg_key = os.getenv("IRIS_MAILGUARD_API_KEY", "").strip()
    iris_url = get_settings().iris_api_url.rstrip("/")
    endpoint = iris_url + _IRIS_SPAM_ENDPOINT

    db = SessionLocal()
    try:
        state = get_sync_state(db)
        last_sync_at = state.get("last_sync_at")

        # ── Apel IRIS API ─────────────────────────────────────────────────────
        try:
            params = {}
            if last_sync_at:
                params["since"] = last_sync_at  # IRIS filtrează delta dacă suportă
            with httpx.Client(timeout=30, verify=False) as cl:
                r = cl.get(endpoint, headers={"X-Mailguard-Key": mg_key}, params=params)
            if r.status_code == 404:
                err = f"Endpoint IRIS {_IRIS_SPAM_ENDPOINT} inexistent (404) — confirmați path-ul cu admin IRIS"
                logger.error("cts_spam_sync: %s", err)
                state.update({"last_error": err, "last_error_at": datetime.now(timezone.utc).isoformat()})
                _save_state(db, state)
                return {"ok": False, "error": err}
            if r.status_code != 200:
                err = f"IRIS API {r.status_code}: {r.text[:200]}"
                logger.error("cts_spam_sync: %s", err)
                state.update({"last_error": err, "last_error_at": datetime.now(timezone.utc).isoformat()})
                _save_state(db, state)
                return {"ok": False, "error": err}
            rows = r.json()
            if not isinstance(rows, list):
                rows = rows.get("data") or rows.get("items") or rows.get("results") or []
        except Exception as e:
            err = f"Apel IRIS API eșuat: {str(e)[:200]}"
            logger.error("cts_spam_sync: %s", err)
            state.update({"last_error": err, "last_error_at": datetime.now(timezone.utc).isoformat()})
            _save_state(db, state)
            return {"ok": False, "error": err}

        # ── Sync în MG blacklist ──────────────────────────────────────────────
        added = skipped = errors = 0
        new_entries = []

        for row in rows:
            # Suportă atât {"email": "x@y.com"} cât și string simplu
            if isinstance(row, str):
                email_addr = row.strip().lower()
                cts_user = "cts"
            else:
                email_addr = (row.get("email") or "").strip().lower()
                cts_user = row.get("created_by") or row.get("added_by") or "cts"
            if not email_addr:
                continue
            actor = f"cts_spam_sync:{cts_user}"
            try:
                res = sender_lists.add_entry(
                    db, "blacklist", email_addr, actor,
                    source="cts_spam_sync", tip="spam", commit=False,
                )
                if res.get("ok"):
                    added += 1
                    new_entries.append(email_addr)
                elif res.get("conflict"):
                    skipped += 1  # pe whitelist MG — respectă decizia umană
                else:
                    skipped += 1
            except Exception as ex:
                logger.exception("cts_spam_sync add_entry failed for %s", email_addr)
                errors += 1

        if added > 0:
            db.commit()

        now_iso = datetime.now(timezone.utc).isoformat()
        state.update({
            "last_sync_at": now_iso,
            "last_added": added,
            "last_skipped": skipped,
            "last_errors": errors,
            "last_count": len(rows),
            "last_triggered_by": triggered_by,
            "last_error": None,
            "last_error_at": None,
            "total_synced": (state.get("total_synced") or 0) + added,
        })
        _save_state(db, state)
        logger.info("cts_spam_sync ok: added=%d skipped=%d errors=%d rows=%d",
                    added, skipped, errors, len(rows))
        return {
            "ok": True,
            "added": added,
            "skipped": skipped,
            "errors": errors,
            "rows_from_iris": len(rows),
            "last_sync_at": now_iso,
            "new_entries": new_entries[:100],
        }

    except Exception as e:
        logger.exception("cts_spam_sync unexpected error")
        return {"ok": False, "error": str(e)[:300]}
    finally:
        db.close()
