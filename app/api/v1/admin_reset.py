"""Reset & reimport emailuri (buton de intretinere).

Sterge TOATE emailurile + atasamentele + extragerile de documente (PASTREAZA document_types,
suppression_rules, prompturile), reimporta din parser de la o data X incoace, le trece prin
categorisire, pune ~20%% din zilele reimportate (mai putin azi) in Verificare manuala (fine-tuning),
iar documentele se proceseaza DOAR daca toggle-ul documents.auto_processing e pornit.

Distructiv: backup-ul se face inainte (operatorul/agentul ruleaza pg_dump). Wipe-ul e o tranzactie
unica, FK-safe (vezi topologia in cod). Orchestrarea ruleaza intr-un daemon thread; progresul e in
settings['admin.reset_state'].
"""
import json
import logging
import threading
import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text

from app.database import SessionLocal
from app.api.v1.auth import get_current_admin

logger = logging.getLogger("mailguard.admin_reset")
router = APIRouter()

_STATE_KEY = "admin.reset_state"
_lock = threading.Lock()


def _set_state(db, st: dict):
    db.execute(text(
        "INSERT INTO settings(key, value, updated_by, updated_at) "
        "VALUES(:k, CAST(:v AS jsonb), 'iris', NOW()) "
        "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_by='iris', updated_at=NOW()"),
        {"k": _STATE_KEY, "v": json.dumps(st)})
    db.commit()


def _get_state(db):
    r = db.execute(text("SELECT value FROM settings WHERE key=:k"), {"k": _STATE_KEY}).fetchone()
    return r[0] if r else None


def _wipe(db):
    """Sterge toate emailurile + dependentele, FK-safe, intr-o singura tranzactie.
    CASCADE: attachments->document_extractions, email_spam, quarantine_strict.
    NO ACTION (sterse explicit intai): delivery_queue, ndr_log, quarantine_feedback,
    spam_unsubscribe_log. suppression_rules.from_feedback_id -> quarantine_feedback (null intai,
    pastram regulile). extraction_queue/extracted_records: orfane fara FK -> golite.
    NU atinge: document_types, suppression_rules (doar null pe from_feedback_id), prompturi, settings."""
    db.execute(text("UPDATE suppression_rules SET from_feedback_id=NULL WHERE from_feedback_id IS NOT NULL"))
    for t in ("delivery_queue", "ndr_log", "quarantine_feedback", "spam_unsubscribe_log",
              "extraction_queue", "extracted_records"):
        db.execute(text("DELETE FROM %s" % t))
    db.execute(text("DELETE FROM emails"))
    # reset gate pick zilnic ca sa poata rula iar pe datele noi
    db.execute(text("DELETE FROM settings WHERE key='manual_review.last_batch'"))
    db.commit()


def _today_yesterday():
    db = SessionLocal()
    try:
        today = db.execute(text("SELECT (now() AT TIME ZONE 'Europe/Bucharest')::date")).scalar()
    finally:
        db.close()
    return today, (today - datetime.timedelta(days=1))


def _run_reset(from_date: str):
    import os as _os
    from app.services import parser_email_op_reader, process_email, o365_ingest
    from app.api.v1 import documents
    db = SessionLocal()
    st = {"running": True, "step": "start", "from_date": from_date, "counts": {}, "error": None}
    try:
        _set_state(db, st)

        st["step"] = "wipe"; _set_state(db, st)
        _wipe(db)

        st["step"] = "reimport"; _set_state(db, st)
        # Sursa de reimport urmeaza acelasi gating ca /sync/run-now: pe staging
        # MAILGUARD_NATIVE_INGEST=on => O365 native; altfel parser-email-op (legacy/prod).
        if _os.getenv("MAILGUARD_NATIVE_INGEST", "off").lower() == "on":
            sync = o365_ingest.backfill_from_date(from_date)
        else:
            sync = parser_email_op_reader.sync_run(from_date=from_date)
        if not sync.get("ok", True):
            raise RuntimeError(sync.get("error") or "reimport esuat")
        st["counts"]["reimport"] = sync; _set_state(db, st)

        st["step"] = "categorize"; _set_state(db, st)
        total = {"processed": 0}
        for _ in range(60):  # garda anti-bucla (60*500 = 30k emailuri)
            r = process_email.process_pending_batch(limit=500)
            try:
                process_email.advance_queue_batch(limit=500)
            except Exception:
                logger.exception("advance_queue_batch failed")
            n = r.get("processed", 0)
            total["processed"] += n
            if n == 0:
                break
        st["counts"]["categorize"] = total; _set_state(db, st)

        st["step"] = "documents"; _set_state(db, st)
        if documents._auto_enabled():
            documents._kick_drain("all", force=True)
            st["counts"]["documents"] = "drain pornit (toggle ON) — ruleaza in fundal"
        else:
            st["counts"]["documents"] = "skip (toggle Procesare documente OPRIT)"
        _set_state(db, st)

        st["running"] = False; st["step"] = "done"
        st["finished_at"] = str(datetime.datetime.now())
        _set_state(db, st)
        logger.info("reset-reimport done: %s", st["counts"])
    except Exception as e:
        logger.exception("reset-reimport failed")
        st["running"] = False; st["step"] = "error"; st["error"] = str(e)[:500]
        try:
            _set_state(db, st)
        except Exception:
            pass
    finally:
        db.close()
        _lock.release()


def _wipe_range(db, start_date: str, end_date: str):
    """Sterge emailurile primite in intervalul [start_date, end_date] (inclusiv ambele capete).
    FK-safe: CASCADE pe attachments->document_extractions. Sterge explicit randurile din
    tabelele NO ACTION pentru emailurile din interval. Pastreaza tot ce e in afara intervalului."""
    # Gaseste email ID-urile din interval
    ids_rows = db.execute(text(
        "SELECT id FROM emails WHERE received_at::date BETWEEN :s AND :e"
    ), {"s": start_date, "e": end_date}).fetchall()
    ids = [r[0] for r in ids_rows]
    if not ids:
        return 0
    # Sterge dependente NO ACTION pentru emailurile din interval
    db.execute(text("UPDATE suppression_rules SET from_feedback_id=NULL "
                    "WHERE from_feedback_id IN "
                    "(SELECT id FROM quarantine_feedback WHERE email_id = ANY(:ids))"),
               {"ids": ids})
    for tbl in ("delivery_queue", "ndr_log", "quarantine_feedback",
                "spam_unsubscribe_log", "extraction_queue", "extracted_records"):
        db.execute(text("DELETE FROM %s WHERE email_id = ANY(:ids)" % tbl), {"ids": ids})
    db.execute(text("DELETE FROM emails WHERE id = ANY(:ids)"), {"ids": ids})
    db.commit()
    return len(ids)


def _run_reimport_range(start_date: str, end_date: str):
    import os as _os
    from app.services import parser_email_op_reader, process_email, o365_ingest
    from app.api.v1 import documents
    db = SessionLocal()
    _STATE_RANGE_KEY = "admin.reimport_range_state"

    def _set(st):
        db.execute(text(
            "INSERT INTO settings(key, value, updated_by, updated_at) "
            "VALUES(:k, CAST(:v AS jsonb), 'iris', NOW()) "
            "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_by='iris', updated_at=NOW()"),
            {"k": _STATE_RANGE_KEY, "v": json.dumps(st)})
        db.commit()

    st = {"running": True, "step": "start", "start_date": start_date, "end_date": end_date,
          "counts": {}, "error": None}
    try:
        _set(st)

        st["step"] = "wipe_range"; _set(st)
        n_wiped = _wipe_range(db, start_date, end_date)
        st["counts"]["wiped_emails"] = n_wiped; _set(st)

        st["step"] = "reimport"; _set(st)
        if _os.getenv("MAILGUARD_NATIVE_INGEST", "off").lower() == "on":
            sync = o365_ingest.backfill_from_date(start_date, to_date=end_date)
        else:
            sync = parser_email_op_reader.sync_run(from_date=start_date, to_date=end_date)
        if not sync.get("ok", True):
            raise RuntimeError(sync.get("error") or "reimport esuat")
        st["counts"]["reimport"] = sync; _set(st)

        st["step"] = "categorize"; _set(st)
        total = {"processed": 0}
        for _ in range(60):
            r = process_email.process_pending_batch(limit=500)
            try:
                process_email.advance_queue_batch(limit=500)
            except Exception:
                logger.exception("advance_queue_batch failed (range)")
            n = r.get("processed", 0)
            total["processed"] += n
            if n == 0:
                break
        st["counts"]["categorize"] = total; _set(st)

        st["step"] = "documents"; _set(st)
        if documents._auto_enabled():
            documents._kick_drain("all", force=True)
            st["counts"]["documents"] = "drain pornit (toggle ON) — ruleaza in fundal"
        else:
            st["counts"]["documents"] = "skip (toggle Procesare documente OPRIT)"
        _set(st)

        st["running"] = False; st["step"] = "done"
        st["finished_at"] = str(datetime.datetime.now())
        _set(st)
        logger.info("reimport-range done: %s", st["counts"])
    except Exception as e:
        logger.exception("reimport-range failed")
        st["running"] = False; st["step"] = "error"; st["error"] = str(e)[:500]
        try:
            _set(st)
        except Exception:
            pass
    finally:
        db.close()
        _lock.release()


@router.post("/admin/reset-reimport")
def reset_reimport(from_date: str = Query(..., description="YYYY-MM-DD"),
                   admin=Depends(get_current_admin)):
    """Distructiv: sterge toate emailurile + reimporta de la from_date incoace. Async (daemon)."""
    try:
        datetime.date.fromisoformat(from_date)
    except Exception:
        raise HTTPException(status_code=400, detail="from_date invalid (asteptat YYYY-MM-DD)")
    if not _lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Un reset este deja in curs")
    threading.Thread(target=_run_reset, args=(from_date,), daemon=True).start()
    return {"ok": True, "started": True, "from_date": from_date}


@router.post("/admin/reimport-range")
def reimport_range(start_date: str = Query(..., description="YYYY-MM-DD"),
                   end_date: str = Query(..., description="YYYY-MM-DD"),
                   admin=Depends(get_current_admin)):
    """Sterge si reimporta DOAR emailurile din intervalul [start_date, end_date].
    Emailurile din afara intervalului raman intacte. Async (daemon)."""
    try:
        s = datetime.date.fromisoformat(start_date)
        e = datetime.date.fromisoformat(end_date)
    except Exception:
        raise HTTPException(status_code=400, detail="start_date/end_date invalide (asteptat YYYY-MM-DD)")
    if s > e:
        raise HTTPException(status_code=400, detail="start_date trebuie sa fie <= end_date")
    if (e - s).days > 31:
        raise HTTPException(status_code=400, detail="Intervalul maxim este 31 de zile")
    if not _lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Un reset/reimport este deja in curs")
    threading.Thread(target=_run_reimport_range, args=(start_date, end_date), daemon=True).start()
    return {"ok": True, "started": True, "start_date": start_date, "end_date": end_date}


@router.get("/admin/reset-reimport/status")
def reset_status(admin=Depends(get_current_admin)):
    db = SessionLocal()
    try:
        return {"ok": True, "state": _get_state(db), "running": _lock.locked()}
    finally:
        db.close()
