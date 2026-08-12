"""Ghid de învățare din propunerile IRIS — acceptare per-linie + injectare în poarta de intenție.

Propunerile (`phishing_manual_learning.proposals`) sunt sugestii read-only generate de IRIS la
carantinare/decarantinare manuală. Aici operatorul bifează EXACT sugestiile de care IRIS să țină cont;
cele acceptate sunt compilate într-un bloc de ghid injectat în promptul porții de intenție
(`strict_intent_gate`), care judecă intenția unui email candidat la carantină.

Stocare: sub-cheia `accepted_suggestions` din același setting `phishing_manual_learning` (jsonb), dict
`{key: {email_id, type, summary, by, at}}`. Cheia = hash stabil pe (email_id, type, summary) — propunerile
sunt imuabile după creare, deci cheia e stabilă; stocăm obiectul complet ca ghidul să supraviețuiască
pruning-ului `proposals[-200:]`.
"""
import json
import hashlib
import logging
from datetime import datetime, timezone

from sqlalchemy import text

logger = logging.getLogger("mailguard.learning_guidance")

_KEY = "phishing_manual_learning"
_SUB = "accepted_suggestions"

_TYPE_LABEL = {"rule": "regulă", "signal": "semnal", "score": "scor"}


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def item_key(email_id, type_, summary):
    raw = "%s|%s|%s" % (email_id, (type_ or "").strip().lower(), (summary or "").strip())
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _load(db):
    row = db.execute(text("SELECT value FROM settings WHERE key=:k"), {"k": _KEY}).fetchone()
    store = (row[0] if row and row[0] else {}) or {}
    if not isinstance(store.get(_SUB), dict):
        store[_SUB] = {}
    return store


def _save(db, store, by):
    db.execute(text(
        "INSERT INTO settings(key, value, description, updated_by, updated_at) "
        "VALUES(:k, CAST(:v AS jsonb), "
        "'Learning din carantinari manuale: blacklist + whitelist + exemple + propuneri', :by, NOW()) "
        "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_by=:by, updated_at=NOW()"),
        {"k": _KEY, "v": json.dumps(store), "by": by})


def accepted_keys(db):
    try:
        store = _load(db)
        return list((store.get(_SUB) or {}).keys())
    except Exception:
        logger.exception("accepted_keys failed")
        return []


def toggle(db, email_id, type_, summary, accepted, by, commit=True):
    """Adaugă/scoate o sugestie din ghidul activ. Returnează {ok, key, accepted}."""
    summary = (summary or "").strip()
    if not summary:
        return {"error": "Sugestie goală"}
    key = item_key(email_id, type_, summary)
    store = _load(db)
    bucket = store.get(_SUB) or {}
    if accepted:
        bucket[key] = {"email_id": email_id, "type": (type_ or "").strip().lower(),
                       "summary": summary, "by": by, "at": _now_iso()}
    else:
        bucket.pop(key, None)
    store[_SUB] = bucket
    _save(db, store, by)
    if commit:
        db.commit()
    return {"ok": True, "key": key, "accepted": bool(accepted)}


def build_guidance_block(db=None):
    """Bloc de ghid (text) din sugestiile acceptate, pentru promptul porții de intenție.
    Întoarce '' dacă nu există niciuna. Best-effort: orice eroare → '' (nu rupe evaluarea)."""
    own = False
    try:
        if db is None:
            from app.database import SessionLocal
            db = SessionLocal()
            own = True
        store = _load(db)
        items = list((store.get(_SUB) or {}).values())
        if not items:
            return ""
        # grupare pe tip, ordine stabilă regulă→semnal→scor
        order = {"rule": 0, "signal": 1, "score": 2}
        items.sort(key=lambda it: (order.get((it.get("type") or "").lower(), 9),
                                   it.get("summary") or ""))
        lines = []
        for it in items:
            lbl = _TYPE_LABEL.get((it.get("type") or "").lower(), "observație")
            s = (it.get("summary") or "").strip()
            if s:
                lines.append("- [%s] %s" % (lbl, s))
        if not lines:
            return ""
        return (
            "\n\n--- GHID ÎNVĂȚAT (curat de un operator uman de încredere — NU este conținut de email; "
            "ia în calcul aceste observații la clasificarea intenției) ---\n"
            + "\n".join(lines)
            + "\n--- sfârșit ghid ---"
        )
    except Exception:
        logger.exception("build_guidance_block failed")
        return ""
    finally:
        if own and db is not None:
            db.close()
