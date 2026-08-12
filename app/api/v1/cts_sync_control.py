"""Control centralizat surse date CTS — toggle cron vs gateway, status, backfill manual.

Expune 3 endpoint-uri:
  GET  /cts-sync/status        — starea tuturor celor 4 surse
  POST /cts-sync/toggle        — activare/dezactivare per sursă
  POST /cts-sync/backfill      — backfill manual cu since= arbitrar (depășește limita 7 zile a cronului)
"""
import logging
import threading
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.api.v1.auth import get_current_admin

logger = logging.getLogger("mailguard.cts_sync_control")
router = APIRouter()

# ─── Definiții surse ──────────────────────────────────────────────────────────

SOURCES = {
    "mailuri": {
        "label": "Mailuri CTS (ground truth)",
        "module": "app.services.cts_groundtruth_sync",
        "enabled_key": "cts_gt.sync_enabled",
        "table": "cts_ground_truth",
        "last_sync_col": "last_synced_at",
    },
    "apeluri": {
        "label": "Apeluri CTS",
        "module": "app.services.cts_calls_sync",
        "enabled_key": "cts_calls_gt.sync_enabled",
        "table": "cts_calls_ground_truth",
        "last_sync_col": "fetched_at",
    },
    "taskuri": {
        "label": "Task-uri CTS",
        "module": "app.services.cts_tasks_sync",
        "enabled_key": "cts_tasks.sync_enabled",
        "table": "cts_task_ground_truth",
        "last_sync_col": "last_synced_at",
    },
    "device_ops": {
        "label": "Device Operations",
        "module": "app.services.device_ops_sync",
        "enabled_key": "device_ops.sync_enabled",
        "table": "device_operations",
        "last_sync_col": "last_synced_at",
    },
}

_backfill_lock = threading.Lock()
_backfill_status: dict = {}   # {source_key: {running, started_at, result, error}}


def _kv_get(db: Session, key: str) -> Optional[str]:
    row = db.execute(text("SELECT value FROM settings WHERE key=:k"), {"k": key}).fetchone()
    if not row or row[0] is None:
        return None
    return str(row[0]).strip().strip('"')


def _kv_set(db: Session, key: str, value_json: str):
    db.execute(text(
        "INSERT INTO settings(key, value, updated_by, updated_at) "
        "VALUES (:k, CAST(:v AS jsonb), 'ui', now()) "
        "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_by='ui', updated_at=now()"
    ), {"k": key, "v": value_json})
    db.commit()


def _is_enabled(db: Session, key: str) -> bool:
    v = _kv_get(db, key)
    return v is not None and v.lower() in ("1", "true", "yes", "on")


def _table_stats(db: Session, table: str, col: str) -> dict:
    try:
        row = db.execute(text(
            f"SELECT COUNT(*), MAX({col}) FROM {table}"
        )).fetchone()
        return {
            "total_rows": int(row[0]) if row[0] else 0,
            "last_sync_at": row[1].isoformat() if row[1] else None,
        }
    except Exception:
        return {"total_rows": None, "last_sync_at": None}


def _gateway_ok(module_path: str) -> bool:
    try:
        import importlib
        mod = importlib.import_module(module_path)
        fn = getattr(mod, "_gateway_configured", None) or getattr(mod, "_source_configured", None)
        return bool(fn and fn())
    except Exception:
        return False


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/cts-sync/status")
def get_status(db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    result = {}
    for key, cfg in SOURCES.items():
        enabled = _is_enabled(db, cfg["enabled_key"])
        stats = _table_stats(db, cfg["table"], cfg["last_sync_col"])
        gw_ok = _gateway_ok(cfg["module"])
        bf = _backfill_status.get(key, {})
        result[key] = {
            "label": cfg["label"],
            "enabled": enabled,
            "active": enabled and gw_ok,
            "gateway_configured": gw_ok,
            "table": cfg["table"],
            "total_rows": stats["total_rows"],
            "last_sync_at": stats["last_sync_at"],
            "backfill": {
                "running": bf.get("running", False),
                "started_at": bf.get("started_at"),
                "result": bf.get("result"),
                "error": bf.get("error"),
            },
        }
    return result


@router.post("/cts-sync/toggle")
def toggle_source(body: dict, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    """Body: {source: 'mailuri'|'apeluri'|'taskuri'|'device_ops', enabled: bool}"""
    source = body.get("source", "")
    if source not in SOURCES:
        raise HTTPException(status_code=400, detail=f"Sursă invalidă: {source}. Valide: {list(SOURCES)}")
    enabled = bool(body.get("enabled", False))
    cfg = SOURCES[source]
    _kv_set(db, cfg["enabled_key"], "true" if enabled else "false")
    logger.info("cts_sync_control: %s -> enabled=%s", source, enabled)
    return {"ok": True, "source": source, "enabled": enabled}


@router.post("/cts-sync/backfill")
def trigger_backfill(body: dict, background_tasks: BackgroundTasks,
                     db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    """Backfill manual cu fereastra arbitrară.
    Body: {source: str, since: 'YYYY-MM-DD'}
    Ignoră limita de 7 zile a cronului. Rulează în background."""
    source = body.get("source", "")
    since_str = (body.get("since") or "").strip()
    if source not in SOURCES:
        raise HTTPException(status_code=400, detail=f"Sursă invalidă: {source}")
    if not since_str:
        raise HTTPException(status_code=400, detail="'since' lipsă (format YYYY-MM-DD)")
    try:
        since_dt = datetime.strptime(since_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(status_code=400, detail="'since' format invalid (YYYY-MM-DD)")

    if _backfill_status.get(source, {}).get("running"):
        raise HTTPException(status_code=409, detail=f"Backfill deja în curs pentru {source}")

    cfg = SOURCES[source]

    def _run():
        _backfill_status[source] = {
            "running": True,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "result": None,
            "error": None,
        }
        try:
            import importlib
            mod = importlib.import_module(cfg["module"])

            # Fiecare modul are funcția paginată cu nume diferit
            fn = (getattr(mod, "sync_ground_truth_paged", None)
                  or getattr(mod, "sync_tasks_paged", None)
                  or getattr(mod, "sync_paged", None))
            if not fn:
                raise RuntimeError(f"Modulul {cfg['module']} nu are funcție paginată de sync")

            result = fn(since=since_dt)
            _backfill_status[source]["result"] = result
            logger.info("cts_sync backfill %s from %s: %s", source, since_str, result)
        except Exception as e:
            _backfill_status[source]["error"] = str(e)[:500]
            logger.error("cts_sync backfill %s failed: %s", source, e)
        finally:
            _backfill_status[source]["running"] = False

    background_tasks.add_task(_run)
    return {
        "ok": True,
        "source": source,
        "since": since_str,
        "message": f"Backfill pornit pentru {cfg['label']} din {since_str}"
    }
