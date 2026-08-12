"""Asignare email pe UTILIZATOR — reclasificare per-email, corectii (learning), stats, reclasificare
in fundal. Mirror al ai_department.py (OPS-2026-0131).

Emailurile noi primesc asignare automat in pipeline (process_email._maybe_classify_assignee).
Aceste endpoint-uri permit rerularea unui email, corectia manuala si reincadrarea in masa pentru
backfill (ca statisticile vs CTS sa aiba date).

STRICT: asignam doar cand o persoana CargoTrack e identificabila cert in fir; altfel ai_assignee=NULL.
"""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import get_db
from app.api.v1.auth import get_current_admin
from app.services import assignee_classifier as A
from app.services import iris_ai

logger = logging.getLogger("mailguard.ai_assignee")
router = APIRouter()

# Coloanele de care are nevoie clasificatorul (lectia OPS-2026-0129: SELECT complet, altfel
# context/istoric gol in tacere).
_SEL = ("SELECT id, subject, from_address, from_name, conversation_id, received_at, "
        "body_text, body_html, ai_department FROM emails WHERE id=:id")


def _classify_and_store(db: Session, email_id: int) -> dict:
    row = db.execute(text(_SEL), {"id": email_id}).fetchone()
    if not row:
        raise HTTPException(404, "Email not found")
    res = A.classify_assignee(dict(row._mapping))
    db.execute(text(
        "UPDATE emails SET ai_assignee=:a, ai_assignee_result=CAST(:r AS jsonb), "
        "ai_assignee_at=NOW() WHERE id=:id AND ai_assignee_manual IS NOT TRUE"),
        {"a": res.get("assignee_email"), "r": json.dumps(res), "id": email_id})
    db.commit()
    return res


def _employee_by_email(db: Session, email: str):
    return db.execute(text(
        "SELECT id, name, email, department FROM employee_department_mapping "
        "WHERE lower(email)=lower(:e) AND enabled=TRUE"), {"e": email}).fetchone()


@router.post("/ai/assignee/{email_id}/run")
def assignee_run_one(email_id: int, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """(Re)asigneaza un singur email — dupa editarea promptului sau pentru verificare."""
    res = _classify_and_store(db, email_id)
    return {"ok": True, "email_id": email_id, "ai_assignee": res.get("assignee_email"),
            "ai_assignee_result": res}


@router.post("/ai/assignee/{email_id}/correct")
def assignee_correct(email_id: int, body: dict, db: Session = Depends(get_db),
                     admin=Depends(get_current_admin)):
    """Corecteaza manual asignarea. assignee_email gol/null => dezasignare explicita (neasignat).
    Alimenteaza ai_assignee_corrections. Seteaza ai_assignee_manual=TRUE."""
    new_email = (body.get("assignee_email") or "").strip() or None
    emp = None
    if new_email:
        emp = _employee_by_email(db, new_email)
        if not emp:
            raise HTTPException(400, "Utilizator inexistent sau inactiv in lista (Setari -> Utilizatori).")
        new_email = emp._mapping["email"]
    row = db.execute(text("SELECT ai_assignee, ai_assignee_result FROM emails WHERE id=:id"),
                     {"id": email_id}).fetchone()
    if not row:
        raise HTTPException(404, "Email not found")
    old_email = row._mapping["ai_assignee"]
    old_reason = None
    try:
        old_reason = (row._mapping["ai_assignee_result"] or {}).get("reason")
    except Exception:
        pass
    reviewer = admin.get("username") or admin.get("email") or "admin"
    db.execute(text(
        "INSERT INTO ai_assignee_corrections(email_id, old_assignee, new_assignee, old_reason, corrected_by) "
        "VALUES(:e, :o, :n, :r, :by)"),
        {"e": email_id, "o": old_email, "n": new_email, "r": old_reason, "by": reviewer})
    new_result = {
        "assignee_email": new_email,
        "assignee_name": (emp._mapping["name"] if emp else None),
        "assignee_id": (emp._mapping["id"] if emp else None),
        "department": (emp._mapping["department"] if emp else None),
        "confidence": 1.0, "reason": "Corectat manual de " + reviewer,
        "model": "manual", "manual": True}
    db.execute(text(
        "UPDATE emails SET ai_assignee=:a, ai_assignee_result=CAST(:r AS jsonb), "
        "ai_assignee_manual=TRUE, ai_assignee_at=NOW() WHERE id=:id"),
        {"a": new_email, "r": json.dumps(new_result), "id": email_id})
    db.commit()
    return {"ok": True, "email_id": email_id, "old_assignee": old_email,
            "new_assignee": new_email, "ai_assignee_result": new_result}


@router.get("/ai/assignee/employees")
def assignee_employees(db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Lista utilizatorilor activi (pt. dropdown-ul de corectie din UI)."""
    rows = db.execute(text(
        "SELECT email, name, department FROM employee_department_mapping "
        "WHERE enabled=TRUE AND email IS NOT NULL AND email <> '' ORDER BY name")).fetchall()
    return {"employees": [dict(r._mapping) for r in rows]}


@router.get("/ai/assignee/corrections")
def assignee_corrections(limit: int = Query(200, ge=1, le=2000),
                         db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Corectii manuale de asignare: vechi vs nou."""
    rows = db.execute(text(
        "SELECT c.id, c.email_id, c.old_assignee, c.new_assignee, c.old_reason, c.corrected_by, "
        "to_char(c.created_at,'YYYY-MM-DD HH24:MI') AS created_at, "
        "e.subject, e.from_address, e.ai_assignee AS current_assignee "
        "FROM ai_assignee_corrections c JOIN emails e ON e.id=c.email_id "
        "ORDER BY c.id DESC LIMIT :l"), {"l": limit}).fetchall()
    total = db.execute(text("SELECT count(*) FROM ai_assignee_corrections")).scalar()
    return {"total": total, "items": [dict(r._mapping) for r in rows]}


@router.delete("/ai/assignee/corrections")
def assignee_corrections_reset(db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Reset: sterge TOATE corectiile de asignare. Ireversibil."""
    n = db.execute(text("SELECT count(*) FROM ai_assignee_corrections")).scalar() or 0
    db.execute(text("DELETE FROM ai_assignee_corrections"))
    db.commit()
    return {"ok": True, "deleted": int(n)}


@router.get("/ai/assignee/stats")
def assignee_stats(db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Distributie pe assignee + numar asignate / neasignate / pentru review."""
    by_asg = db.execute(text(
        "SELECT e.ai_assignee AS assignee, em.name AS assignee_name, count(*) AS n "
        "FROM emails e LEFT JOIN employee_department_mapping em ON lower(em.email)=lower(e.ai_assignee) "
        "WHERE e.ai_assignee IS NOT NULL GROUP BY e.ai_assignee, em.name ORDER BY n DESC")).fetchall()
    totals = db.execute(text(
        "SELECT count(*) FILTER (WHERE ai_assignee IS NOT NULL) AS assigned, "
        "count(*) FILTER (WHERE ai_assignee IS NULL AND ai_assignee_at IS NOT NULL) AS unassigned, "
        "count(*) FILTER (WHERE ai_assignee_at IS NULL) AS not_processed, "
        "count(*) FILTER (WHERE COALESCE((ai_assignee_result->>'needs_review')::bool, false)) AS needs_review "
        "FROM emails")).fetchone()
    return {
        "configured": iris_ai.is_configured(),
        "totals": dict(totals._mapping),
        "by_assignee": [dict(r._mapping) for r in by_asg],
    }


# ---------------------------------------------------------------------------
# Reasignare in FUNDAL (server-side, fire-and-forget) — mirror al departamentului.
# Marker temporal: ai_assignee_at IS NULL SAU < job_start; sare corectiile manuale.
# ---------------------------------------------------------------------------
import os
import subprocess
import signal as _signal
from datetime import datetime, timezone

_APP_DIR = "/opt/iris-mailguard"
_STATUS_FILE = f"{_APP_DIR}/logs/reclassify_assignee_status.json"
_PY = f"{_APP_DIR}/venv/bin/python"
_STALE_SECONDS = 180


def _read_status():
    try:
        with open(_STATUS_FILE) as f:
            return json.load(f)
    except Exception:
        return None


def _is_alive(st) -> bool:
    if not st or not st.get("running"):
        return False
    try:
        ts = datetime.fromisoformat(st["updated_at"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds() < _STALE_SECONDS
    except Exception:
        return False


def _pending_count(db, st):
    js = (st or {}).get("job_start")
    if not js:
        return None
    conds = ["status <> 'ndr'", "(ai_assignee_manual IS NOT TRUE)",
             "(ai_assignee_at IS NULL OR ai_assignee_at < :js)"]
    params = {"js": js}
    sc = (st or {}).get("scope") or "all"
    if sc.startswith("date:"):
        conds.append("received_at >= :fd"); params["fd"] = sc[5:]
    elif sc.startswith("id:"):
        conds.append("id >= :fid"); params["fid"] = int(sc[3:])
    q = "SELECT count(*) FROM emails WHERE " + " AND ".join(conds)
    return int(db.execute(text(q), params).scalar() or 0)


@router.post("/ai/assignee/reclassify/start")
def asg_reclassify_start(from_date: str = Query(None), from_id: int = Query(None),
                         db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Porneste reasignarea in fundal (toate / de la data / de la id). Sare emailurile corectate
    manual. Continua daca inchizi UI-ul. Dublu-click => intoarce jobul existent."""
    cur = _read_status()
    if _is_alive(cur):
        return {"ok": True, "already_running": True, "status": cur}
    job_start = datetime.now(timezone.utc).isoformat()
    conds = ["status <> 'ndr'", "(ai_assignee_manual IS NOT TRUE)",
             "(ai_assignee_at IS NULL OR ai_assignee_at < :js)"]
    params = {"js": job_start}
    args = [_PY, "-m", "scripts.reclassify_assignee_all", "--job-start", job_start]
    if from_date:
        conds.append("received_at >= :fd"); params["fd"] = from_date
        args += ["--from-date", from_date]
    if from_id is not None:
        conds.append("id >= :fid"); params["fid"] = from_id
        args += ["--from-id", str(from_id)]
    total = db.execute(text("SELECT count(*) FROM emails WHERE " + " AND ".join(conds)), params).scalar()
    subprocess.Popen(args, cwd=_APP_DIR, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
    logger.info("assignee reclassify background started: %s (total=%s)", args, total)
    return {"ok": True, "started": True, "total": int(total or 0),
            "scope": from_date or (("id:" + str(from_id)) if from_id is not None else "all")}


@router.post("/ai/assignee/reclassify/cancel")
def asg_reclassify_cancel(admin=Depends(get_current_admin)):
    st = _read_status()
    if not st or not st.get("running"):
        return {"ok": True, "was_running": False, "note": "Niciun job activ."}
    pid = st.get("pid")
    killed = False
    if pid:
        try:
            os.kill(int(pid), _signal.SIGTERM)
            killed = True
        except ProcessLookupError:
            pass
        except Exception as e:
            logger.warning("assignee cancel kill failed pid=%s: %s", pid, e)
    st["running"] = False
    st["canceled"] = True
    try:
        tmp = _STATUS_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(st, f)
        os.replace(tmp, _STATUS_FILE)
    except Exception:
        pass
    return {"ok": True, "was_running": True, "killed": killed, "processed": st.get("processed", 0)}


@router.get("/ai/assignee/reclassify/status")
def asg_reclassify_status(db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    st = _read_status()
    alive = _is_alive(st)
    out = {"alive": alive, "pending_now": _pending_count(db, st)}
    if st:
        out.update(st)
        if st.get("running") and not alive:
            out["running"] = False
            out["stale"] = True
    return out
