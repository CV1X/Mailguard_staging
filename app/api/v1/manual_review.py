"""Verificare manuală (learning / QA) — listă, statistici, confirmare/corecție, START/STOP.

Modulul eșantionează retrospectiv ~pct% din mailurile CLEAN de ieri pentru ca un
om să confirme/corecteze categoria dată de AI. NU reține nimic de la CTS.
Corecțiile alimentează ai_category_corrections (pagina "Emailuri încadrate greșit").
"""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import get_db
from app.api.v1.auth import get_current_admin
from app.services import manual_review as mr_service

logger = logging.getLogger("mailguard.manual_review_api")
router = APIRouter()

_CATS = ["informatie", "sesizare", "reclamatie", "necunoscut"]


@router.get("/manual-review/status")
def mr_status(db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    return {
        "enabled": bool(mr_service.get_setting(db, "manual_review.enabled", True)),
        "pct": mr_service.get_setting(db, "manual_review.pct", 20),
        "last_batch": mr_service.get_setting(db, "manual_review.last_batch", None),
    }


@router.post("/manual-review/toggle")
def mr_toggle(body: dict, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    enabled = bool(body.get("enabled"))
    mr_service.set_setting(db, "manual_review.enabled", enabled)
    db.commit()
    return {"ok": True, "enabled": enabled}


@router.post("/manual-review/run-batch")
def mr_run_batch(_admin=Depends(get_current_admin)):
    """Declanșează manual pick-ul pentru ieri (idempotent)."""
    return mr_service.run_daily_pick_if_due()


@router.get("/manual-review/queue")
def mr_queue(state: str = Query("pending"), limit: int = Query(50, ge=1, le=500),
             offset: int = Query(0, ge=0),
             db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    st = state if state in ("pending", "done") else "pending"
    rows = db.execute(text(
        "SELECT e.id, e.subject, e.from_address, e.from_name, e.to_addresses, e.ai_category, e.ai_department, "
        "CASE WHEN jsonb_typeof(e.ai_result->'confidence')='number' "
        "     THEN (e.ai_result->>'confidence')::float END AS confidence, "
        "e.ai_result->>'reason' AS reason, "
        "e.manual_review_reason, e.manual_review_result, e.manual_review_by, "
        "corr.old_category AS mr_old_category, (corr.id IS NOT NULL) AS mr_cat_corrected, "
        "dcorr.old_department AS mr_old_department, (dcorr.id IS NOT NULL) AS mr_dept_corrected, "
        "e.ai_priority, pcorr.old_priority AS mr_old_priority, (pcorr.id IS NOT NULL) AS mr_pri_corrected, "
        "to_char(e.manual_review_done_at AT TIME ZONE 'Europe/Bucharest','YYYY-MM-DD HH24:MI') AS done_at, "
        "to_char(e.received_at AT TIME ZONE 'Europe/Bucharest','YYYY-MM-DD HH24:MI') AS received_at, "
        "e.manual_review_batch::text AS batch "
        "FROM emails e "
        "LEFT JOIN LATERAL (SELECT cc.id, cc.old_category FROM ai_category_corrections cc "
        "  WHERE cc.email_id=e.id ORDER BY cc.id DESC LIMIT 1) corr ON TRUE "
        "LEFT JOIN LATERAL (SELECT dc.id, dc.old_department FROM ai_department_corrections dc "
        "  WHERE dc.email_id=e.id ORDER BY dc.id DESC LIMIT 1) dcorr ON TRUE "
        "LEFT JOIN LATERAL (SELECT pc.id, pc.old_priority FROM ai_priority_corrections pc "
        "  WHERE pc.email_id=e.id ORDER BY pc.id DESC LIMIT 1) pcorr ON TRUE "
        "WHERE e.manual_review_state=:s "
        "AND " + mr_service.internal_sender_not_sql("e.from_address") + " "
        "ORDER BY (e.manual_review_reason='unknown') DESC, e.manual_review_picked_at DESC, e.id DESC "
        "LIMIT :l OFFSET :o"),
        {"s": st, "l": limit, "o": offset}).fetchall()
    total = db.execute(text(
        "SELECT count(*) FROM emails WHERE manual_review_state=:s "
        "AND " + mr_service.internal_sender_not_sql("from_address")), {"s": st}).scalar()
    return {"total": total, "items": [dict(r._mapping) for r in rows]}


@router.get("/manual-review/stats")
def mr_stats(db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    row = db.execute(text("""
        SELECT
          (SELECT count(*) FROM emails WHERE status='clean'
             AND (received_at AT TIME ZONE 'Europe/Bucharest')::date
                 = ((now() AT TIME ZONE 'Europe/Bucharest')::date - 1)) AS clean_y,
          (SELECT count(*) FROM emails WHERE status='clean'
             AND ai_category='necunoscut' AND ai_status='done'
             AND (received_at AT TIME ZONE 'Europe/Bucharest')::date
                 = ((now() AT TIME ZONE 'Europe/Bucharest')::date - 1)) AS unknown_y,
          (SELECT count(*) FROM emails WHERE manual_review_state='pending') AS pending,
          (SELECT count(*) FROM emails WHERE manual_review_state='done'
             AND (manual_review_done_at AT TIME ZONE 'Europe/Bucharest')::date
                 = (now() AT TIME ZONE 'Europe/Bucharest')::date) AS done_today,
          (SELECT count(*) FROM emails WHERE manual_review_state='done'
             AND ai_category IS NOT NULL) AS cat_reviewed,
          (SELECT count(DISTINCT c.email_id) FROM ai_category_corrections c
             JOIN emails e ON e.id=c.email_id WHERE e.manual_review_state='done') AS cat_corrected_reviewed,
          (SELECT count(*) FROM emails WHERE manual_review_state='done') AS reviewed,
          (SELECT count(*) FROM emails WHERE manual_review_state IS NOT NULL) AS picked_total,
          -- DEPARTAMENT (a doua axa): acoperire + calitate incadrare
          (SELECT count(*) FROM emails WHERE ai_department IS NOT NULL) AS dept_total,
          (SELECT count(*) FROM emails WHERE ai_department='suport_1') AS dept_suport1,
          (SELECT count(*) FROM emails WHERE ai_department IS NOT NULL
             AND ai_department_result->>'model'='fallback') AS dept_fallback,
          (SELECT count(DISTINCT email_id) FROM ai_department_corrections) AS dept_corrected,
          (SELECT count(*) FROM emails WHERE manual_review_state='done'
             AND ai_department IS NOT NULL) AS dept_reviewed,
          (SELECT count(DISTINCT c.email_id) FROM ai_department_corrections c
             JOIN emails e ON e.id=c.email_id WHERE e.manual_review_state='done') AS dept_corrected_reviewed,
          -- PRIORITATE (a treia axa): acoperire + calitate incadrare
          (SELECT count(*) FROM emails WHERE ai_priority IS NOT NULL) AS pri_total,
          (SELECT count(*) FROM emails WHERE ai_priority='2') AS pri_p1,
          (SELECT count(DISTINCT email_id) FROM ai_priority_corrections) AS pri_corrected,
          (SELECT count(*) FROM emails WHERE manual_review_state='done'
             AND ai_priority IS NOT NULL) AS pri_reviewed,
          (SELECT count(DISTINCT c.email_id) FROM ai_priority_corrections c
             JOIN emails e ON e.id=c.email_id WHERE e.manual_review_state='done') AS pri_corrected_reviewed,
          -- SUGESTIE REPLY AUTO (Faza 1): acoperire + acceptare
          (SELECT count(*) FROM emails WHERE ai_autoreply_status IS NOT NULL) AS ar_total,
          (SELECT count(*) FROM emails WHERE ai_autoreply_status='accepted') AS ar_accepted,
          (SELECT count(*) FROM emails WHERE ai_autoreply_status='rejected') AS ar_rejected,
          (SELECT count(*) FROM emails WHERE ai_autoreply_status='pending') AS ar_pending
    """)).fetchone()
    d = dict(row._mapping)
    clean_y = d["clean_y"] or 0
    reviewed = d["reviewed"] or 0
    # Categorie: confirmat/corectat din corectiile REALE pe categorie (nu din manual_review_result,
    # care e per-email si numara „corectat" si cand s-a schimbat DOAR departamentul -> false-positive).
    cat_reviewed = d.get("cat_reviewed") or 0
    cat_corr = d.get("cat_corrected_reviewed") or 0
    d["corrected"] = cat_corr
    d["confirmed"] = max(0, cat_reviewed - cat_corr)
    conf = d["confirmed"]
    corr = d["corrected"]
    d["unknown_pct_y"] = round(100.0 * (d["unknown_y"] or 0) / clean_y, 1) if clean_y else 0.0
    d["correct_rate"] = round(100.0 * conf / (conf + corr), 1) if (conf + corr) else None
    # Departament: rata de incadrare corecta = printre emailurile verificate manual care AVEAU un
    # departament, cele NEcorectate (absenta unei corectii pe departament). Mirror al ratei pe
    # categorie, dar confirmarea e implicita (operatorul verifica intai categoria).
    dept_total = d["dept_total"] or 0
    dr = d["dept_reviewed"] or 0
    dcr = d["dept_corrected_reviewed"] or 0
    d["dept_confirmed_reviewed"] = dr - dcr
    d["dept_correct_rate"] = round(100.0 * (dr - dcr) / dr, 1) if dr else None
    d["dept_suport1_pct"] = round(100.0 * (d["dept_suport1"] or 0) / dept_total, 1) if dept_total else 0.0
    d["dept_fallback_pct"] = round(100.0 * (d["dept_fallback"] or 0) / dept_total, 1) if dept_total else 0.0
    # Prioritate: rata de incadrare corecta = printre emailurile verificate care AVEAU prioritate,
    # cele NEcorectate (fara corectie de prioritate). Mirror al ratei pe departament.
    pri_total = d["pri_total"] or 0
    pr = d["pri_reviewed"] or 0
    pcr = d["pri_corrected_reviewed"] or 0
    d["pri_confirmed_reviewed"] = pr - pcr
    d["pri_correct_rate"] = round(100.0 * (pr - pcr) / pr, 1) if pr else None
    d["pri_p1_pct"] = round(100.0 * (d["pri_p1"] or 0) / pri_total, 1) if pri_total else 0.0
    # Sugestie reply auto: rata de acceptare printre cele cu verdict uman (accept/reject).
    ar_decided = (d.get("ar_accepted") or 0) + (d.get("ar_rejected") or 0)
    d["ar_accept_rate"] = round(100.0 * (d.get("ar_accepted") or 0) / ar_decided, 1) if ar_decided else None
    return d


def _do_correct(db, email_id, new_cat, reviewer):
    row = db.execute(text(
        "SELECT ai_category, ai_result FROM emails WHERE id=:id"), {"id": email_id}).fetchone()
    if not row:
        raise HTTPException(404, "Email not found")
    old_cat = row._mapping["ai_category"]
    # Guard no-op: re-selectarea ACELEIASI categorii nu e o corectie -> nu scriem rand in
    # ai_category_corrections, nu setam ai_category_manual, nu suprascriem rezultatul AI.
    if (new_cat or "") == (old_cat or ""):
        return old_cat, row._mapping["ai_result"], False
    old_reason = None
    try:
        old_reason = (row._mapping["ai_result"] or {}).get("reason")
    except Exception:
        pass
    db.execute(text(
        "INSERT INTO ai_category_corrections(email_id, old_category, new_category, old_reason, corrected_by) "
        "VALUES(:e, :o, :n, :r, :by)"),
        {"e": email_id, "o": old_cat, "n": new_cat, "r": old_reason, "by": reviewer})
    new_result = {"category": new_cat, "confidence": 1.0,
                  "reason": "Corectat manual (verificare) de " + reviewer, "manual": True}
    # NU finalizam verificarea aici — doar aplicam si logam corectia. Emailul ramane 'pending' ca
    # operatorul sa poata corecta SI departamentul; finalizarea ('done') se face la „Marchează ca
    # corect" (mr_confirm), care marcheaza result='corrected' daca s-a editat ceva.
    db.execute(text(
        "UPDATE emails SET ai_category=:c, ai_result=CAST(:r AS jsonb), ai_category_manual=TRUE, "
        "ai_status='done', ai_processed_at=NOW() WHERE id=:id"),
        {"c": new_cat, "r": json.dumps(new_result), "id": email_id})
    return old_cat, new_result, True


@router.post("/manual-review/{email_id}/confirm")
def mr_confirm(email_id: int, body: dict = None, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Finalizează verificarea manuală (singurul loc care marchează 'done'). Apăsat din „Marchează
    ca corect". body.corrected=true dacă operatorul a editat categoria/departamentul în acest email →
    result='corrected'; altfel result='confirmed' (AI a avut dreptate)."""
    reviewer = admin.get("username") or admin.get("email") or "admin"
    # Sursa de adevar = corectii REALE inregistrate de cand a fost selectat emailul (fereastra
    # verificarii). Ignoram flag-ul „corrected" din frontend (se aprindea la simpla atingere a
    # controlului) => fara false-positive „corectat" pe sectiunea neschimbata.
    picked = db.execute(text(
        "SELECT manual_review_picked_at FROM emails "
        "WHERE id=:id AND manual_review_state='pending'"), {"id": email_id}).fetchone()
    if picked is None:
        raise HTTPException(409, "Emailul nu e în așteptare (deja verificat sau inexistent)")
    win = picked._mapping["manual_review_picked_at"]
    real_cat = db.execute(text(
        "SELECT 1 FROM ai_category_corrections WHERE email_id=:id "
        "AND created_at >= COALESCE(:w, '-infinity'::timestamptz) LIMIT 1"),
        {"id": email_id, "w": win}).fetchone()
    real_dep = db.execute(text(
        "SELECT 1 FROM ai_department_corrections WHERE email_id=:id "
        "AND created_at >= COALESCE(:w, '-infinity'::timestamptz) LIMIT 1"),
        {"id": email_id, "w": win}).fetchone()
    corrected = bool(real_cat or real_dep)
    result = "corrected" if corrected else "confirmed"
    db.execute(text(
        "UPDATE emails SET manual_review_state='done', manual_review_result=:res, "
        "manual_review_done_at=NOW(), manual_review_by=:by "
        "WHERE id=:id AND manual_review_state='pending'"),
        {"res": result, "by": reviewer, "id": email_id})
    db.commit()
    return {"ok": True, "email_id": email_id, "result": result,
            "corrected_category": bool(real_cat), "corrected_department": bool(real_dep)}


@router.post("/manual-review/{email_id}/correct")
def mr_correct(email_id: int, body: dict, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Corectează categoria — alimentează ai_category_corrections și marchează verificat."""
    new_cat = (body.get("category") or "").strip().lower()
    if new_cat not in _CATS:
        raise HTTPException(400, "Categorie invalidă (informatie/sesizare/reclamatie/necunoscut)")
    reviewer = admin.get("username") or admin.get("email") or "admin"
    old_cat, new_result, changed = _do_correct(db, email_id, new_cat, reviewer)
    db.commit()
    return {"ok": True, "email_id": email_id, "old_category": old_cat,
            "new_category": new_cat, "changed": changed,
            "result": ("corrected" if changed else "unchanged"), "ai_result": new_result}


@router.post("/manual-review/{email_id}/correct-department")
def mr_correct_department(email_id: int, body: dict, db: Session = Depends(get_db),
                          admin=Depends(get_current_admin)):
    """Corectează DEPARTAMENTUL din ecranul de verificare manuală: aplică + loghează corecția
    (ai_department_corrections) DAR NU finalizează verificarea — emailul rămâne 'pending' ca
    operatorul să poată corecta și categoria. Finalizarea ('done', result='corrected') se face la
    „Marchează ca corect" (mr_confirm)."""
    from app.services import department_classifier as _D
    new_dep = (body.get("department") or "").strip().lower()
    if new_dep not in _D.DEPARTMENTS:
        raise HTTPException(400, "Departament invalid")
    row = db.execute(text("SELECT ai_department, ai_department_result FROM emails WHERE id=:id"),
                     {"id": email_id}).fetchone()
    if not row:
        raise HTTPException(404, "Email not found")
    old_dep = row._mapping["ai_department"]
    # Guard no-op: acelasi departament -> nu inregistram corectie (altfel stricam statistica).
    if (new_dep or "") == (old_dep or ""):
        return {"ok": True, "email_id": email_id, "old_department": old_dep,
                "new_department": new_dep, "changed": False, "result": "unchanged",
                "ai_department_result": row._mapping["ai_department_result"]}
    old_reason = None
    try:
        old_reason = (row._mapping["ai_department_result"] or {}).get("reason")
    except Exception:
        pass
    reviewer = admin.get("username") or admin.get("email") or "admin"
    db.execute(text(
        "INSERT INTO ai_department_corrections(email_id, old_department, new_department, old_reason, corrected_by) "
        "VALUES(:e, :o, :n, :r, :by)"),
        {"e": email_id, "o": old_dep, "n": new_dep, "r": old_reason, "by": reviewer})
    new_result = {"department": new_dep, "confidence": 1.0,
                  "reason": "Corectat manual (verificare) de " + reviewer, "model": "manual", "manual": True}
    db.execute(text(
        "UPDATE emails SET ai_department=:d, ai_department_result=CAST(:r AS jsonb), "
        "ai_department_manual=TRUE, ai_department_at=NOW() WHERE id=:id"),
        {"d": new_dep, "r": json.dumps(new_result), "id": email_id})
    db.commit()
    return {"ok": True, "email_id": email_id, "old_department": old_dep,
            "new_department": new_dep, "changed": True, "result": "corrected",
            "ai_department_result": new_result}


@router.post("/manual-review/{email_id}/correct-priority")
def mr_correct_priority(email_id: int, body: dict, db: Session = Depends(get_db),
                        admin=Depends(get_current_admin)):
    """Corectează PRIORITATEA (2=plăți / 3=sesizare-reclamație / 4=documente / 5=general) din
    verificarea manuală: aplică + loghează corecția (ai_priority_corrections) DAR NU finalizează."""
    from app.services import priority_classifier as _P
    new_pri = (body.get("priority") or "").strip().upper()
    new_pri = {"P2": "2", "P3": "3", "P4": "4", "P5": "5"}.get(new_pri, new_pri)
    if new_pri not in _P.PRIORITIES:
        raise HTTPException(400, "Prioritate invalida (2, 3, 4 sau 5)")
    row = db.execute(text("SELECT ai_priority, ai_priority_result FROM emails WHERE id=:id"),
                     {"id": email_id}).fetchone()
    if not row:
        raise HTTPException(404, "Email not found")
    old_pri = row._mapping["ai_priority"]
    if (new_pri or "") == (old_pri or ""):
        return {"ok": True, "email_id": email_id, "old_priority": old_pri,
                "new_priority": new_pri, "changed": False, "result": "unchanged",
                "ai_priority_result": row._mapping["ai_priority_result"]}
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
                  "reason": "Corectat manual (verificare) de " + reviewer, "model": "manual", "manual": True}
    db.execute(text(
        "UPDATE emails SET ai_priority=:p, ai_priority_result=CAST(:r AS jsonb), "
        "ai_priority_manual=TRUE, ai_priority_at=NOW() WHERE id=:id"),
        {"p": new_pri, "r": json.dumps(new_result), "id": email_id})
    db.commit()
    return {"ok": True, "email_id": email_id, "old_priority": old_pri,
            "new_priority": new_pri, "changed": True, "result": "corrected",
            "ai_priority_result": new_result}
