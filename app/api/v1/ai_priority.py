"""Incadrare email pe PRIORITATE (P2 plati / P3 sesizare-reclamatie / P4 documente / P5 general)
— stats, reclasificare per-email, corectii (learning) si promptul editabil (single-prompt).

Emailurile noi primesc prioritate automat in pipeline (process_email). Aceste endpoint-uri permit
reclasificarea unui email dupa editarea promptului si gestionarea corectiilor manuale, plus
editarea + versionarea promptului de identificare a prioritatii.

IMPORTANT: corectia de prioritate NU atinge manual_review_state/result (categorie) si nici
ai_department (departament).
"""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import get_db
from app.api.v1.auth import get_current_admin
from app.services import priority_classifier as P
from app.services import iris_ai

logger = logging.getLogger("mailguard.ai_priority")
router = APIRouter()


def _classify_and_store(db: Session, email_id: int) -> dict:
    row = db.execute(text(
        "SELECT id, subject, from_address, from_name, body_text, body_html, ai_category, "
        "ai_op_series "     # fara asta, reincadrarea manuala rateaza regula pay_op_series (OP -> P2)
        "FROM emails WHERE id=:id"), {"id": email_id}).fetchone()
    if not row:
        raise HTTPException(404, "Email not found")
    em = dict(row._mapping)
    res = P.classify_priority(em, category=em.get("ai_category"))   # intoarce "2".."5"
    db.execute(text(
        "UPDATE emails SET ai_priority=:p, ai_priority_result=CAST(:r AS jsonb), "
        "ai_priority_at=NOW() WHERE id=:id"),
        {"p": res["priority"], "r": json.dumps(res), "id": email_id})
    db.commit()
    return res


@router.post("/ai/priority/{email_id}/run")
def priority_run_one(email_id: int, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """(Re)incadreaza pe prioritate un singur email — dupa editarea promptului."""
    res = _classify_and_store(db, email_id)
    return {"ok": True, "email_id": email_id, "ai_priority": res["priority"], "ai_priority_result": res}


@router.post("/ai/priority/{email_id}/correct")
def priority_correct(email_id: int, body: dict, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Corecteaza manual prioritatea unui email (2=plati / 3=sesizare-reclamatie / 4=documente /
    5=general). Alimenteaza fine-tuning-ul (ai_priority_corrections). NU atinge categoria/departamentul."""
    new_pri = (body.get("priority") or "").strip().upper()
    # acceptam si etichetele P2..P5 ca alias, mapate la canonicul "2".."5"
    new_pri = {"P2": "2", "P3": "3", "P4": "4", "P5": "5"}.get(new_pri, new_pri)
    if new_pri not in P.PRIORITIES:
        raise HTTPException(400, "Prioritate invalida (2, 3, 4 sau 5)")
    row = db.execute(text("SELECT ai_priority, ai_priority_result FROM emails WHERE id=:id"),
                     {"id": email_id}).fetchone()
    if not row:
        raise HTTPException(404, "Email not found")
    old_pri = row._mapping["ai_priority"]
    old_reason = None
    try:
        old_reason = (row._mapping["ai_priority_result"] or {}).get("reason")
    except Exception:
        pass
    reviewer = admin.get("username") or admin.get("email") or "admin"
    db.execute(text(
        "INSERT INTO ai_priority_corrections(email_id, old_priority, new_priority, old_reason, corrected_by) "
        "VALUES(:e, :o, :n, :r, :by)"),
        {"e": email_id, "o": old_pri, "n": new_pri, "r": old_reason, "by": reviewer})
    new_result = {"priority": new_pri,
                  "reason": "Corectat manual de " + reviewer, "model": "manual", "manual": True}
    db.execute(text(
        "UPDATE emails SET ai_priority=:p, ai_priority_result=CAST(:r AS jsonb), "
        "ai_priority_manual=TRUE, ai_priority_at=NOW() WHERE id=:id"),
        {"p": new_pri, "r": json.dumps(new_result), "id": email_id})
    db.commit()
    return {"ok": True, "email_id": email_id, "old_priority": old_pri,
            "new_priority": new_pri, "ai_priority_result": new_result}


@router.get("/ai/priority/corrections")
def priority_corrections(limit: int = Query(200, ge=1, le=2000),
                         db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Lista emailurilor incadrate gresit pe prioritate (corectii manuale): vechi vs nou."""
    rows = db.execute(text(
        "SELECT c.id, c.email_id, c.old_priority, c.new_priority, c.old_reason, c.corrected_by, "
        "to_char(c.created_at,'YYYY-MM-DD HH24:MI') AS created_at, "
        "e.subject, e.from_address, e.ai_priority AS current_priority "
        "FROM ai_priority_corrections c JOIN emails e ON e.id=c.email_id "
        "ORDER BY c.id DESC LIMIT :l"), {"l": limit}).fetchall()
    total = db.execute(text("SELECT count(*) FROM ai_priority_corrections")).scalar()
    return {"total": total, "items": [dict(r._mapping) for r in rows]}


@router.delete("/ai/priority/corrections")
def priority_corrections_reset(db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Reset: sterge TOATE corectiile de prioritate. NU atinge promptul. Ireversibil."""
    n = db.execute(text("SELECT count(*) FROM ai_priority_corrections")).scalar() or 0
    db.execute(text("DELETE FROM ai_priority_corrections"))
    db.commit()
    return {"ok": True, "deleted": int(n)}


@router.get("/ai/priority/stats")
def priority_stats(db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    by_pri = db.execute(text(
        "SELECT COALESCE(ai_priority,'(neincadrat)') AS priority, count(*) AS n "
        "FROM emails GROUP BY ai_priority ORDER BY n DESC")).fetchall()
    return {
        "configured": iris_ai.is_configured(),
        "labels": P.PRIORITY_LABELS,
        "by_priority": [dict(r._mapping) for r in by_pri],
    }


# ── Prompt editabil (single-prompt, mirror 'documents.classify-prompt' + versionare) ──

@router.get("/ai/priority/prompt")
def get_priority_prompt(db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Promptul curent de identificare a prioritatii (DB peste default-ul din cod)."""
    return {"ok": True, "prompt": P.load_prompt(), "default": P.DEFAULT_PROMPT,
            "is_default": P.load_prompt() == P.DEFAULT_PROMPT}


@router.put("/ai/priority/prompt")
def put_priority_prompt(body: dict, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Salveaza promptul de prioritate + scrie o versiune in istoric."""
    new_text = (body.get("prompt") or "").strip()
    if len(new_text) < 30:
        raise HTTPException(400, "Prompt prea scurt (minim 30 caractere).")
    reviewer = admin.get("username") or admin.get("email") or "admin"
    source = (body.get("source") or "manual").strip()[:20]
    db.execute(text(
        "INSERT INTO settings(key, value, description, updated_by, updated_at) "
        "VALUES(:k, CAST(:v AS jsonb), 'Prompt identificare prioritate (P2-P5)', :by, NOW()) "
        "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_by=:by, updated_at=NOW()"),
        {"k": P.PROMPT_KEY, "v": json.dumps(new_text), "by": reviewer})
    db.execute(text(
        "INSERT INTO ai_priority_prompt_versions(prompt_text, source, explicatie, based_on, created_by) "
        "VALUES(:t, :s, :e, :b, :by)"),
        {"t": new_text, "s": source, "e": body.get("explicatie"),
         "b": body.get("based_on"), "by": reviewer})
    db.commit()
    return {"ok": True, "note": "Prompt salvat."}


@router.get("/ai/priority/prompt/versions")
def get_priority_prompt_versions(limit: int = Query(50, ge=1, le=500),
                                 db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Istoricul versiunilor de prompt (pentru restaurare in UI)."""
    rows = db.execute(text(
        "SELECT id, prompt_text, source, explicatie, based_on, created_by, "
        "to_char(created_at,'YYYY-MM-DD HH24:MI') AS created_at, length(prompt_text) AS len "
        "FROM ai_priority_prompt_versions ORDER BY id DESC LIMIT :l"), {"l": limit}).fetchall()
    return {"items": [dict(r._mapping) for r in rows]}
