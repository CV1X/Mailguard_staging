"""Sugestie reply auto (Faza 1) — generare per-email, feedback (accept/reject + motiv) si
promptul editabil + versionare. Mirror al lui ai_priority.py.

In Faza 1 sugestia e DOAR informativa (afisata in modal). Emailurile noi primesc o sugestie
automat in pipeline (process_email). Aceste endpoint-uri permit regenerarea pentru un email,
inregistrarea verdictului uman (acceptat = semnal pozitiv; respins = motiv text-liber, pentru
fine-tuning) si editarea + regenerarea promptului pe baza respingerilor.

NU atinge categoria / departamentul / prioritatea / manual_review_state.
"""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import get_db
from app.api.v1.auth import get_current_admin
from app.services import autoreply_generator as A
from app.services import iris_ai

logger = logging.getLogger("mailguard.ai_autoreply")
router = APIRouter()


def _reviewer(admin) -> str:
    return admin.get("username") or admin.get("email") or "admin"


def _generate_and_store(db: Session, email_id: int) -> dict:
    row = db.execute(text(
        "SELECT id, subject, from_address, from_name, body_text, body_html "
        "FROM emails WHERE id=:id"), {"id": email_id}).fetchone()
    if not row:
        raise HTTPException(404, "Email not found")
    res = A.generate_autoreply(dict(row._mapping))
    if not res.get("ok"):
        # Sub prag / expeditor automat / eroare: nu pastram o sugestie veche afisata.
        db.execute(text(
            "UPDATE emails SET ai_autoreply=NULL, ai_autoreply_result=CAST(:r AS jsonb), "
            "ai_autoreply_confidence=:c, ai_autoreply_at=NOW(), ai_autoreply_status=NULL WHERE id=:id"),
            {"r": json.dumps(res), "c": res.get("confidence"), "id": email_id})
        db.commit()
        raise HTTPException(422, res.get("reason") or "Generare esuata")
    db.execute(text(
        "UPDATE emails SET ai_autoreply=:t, ai_autoreply_result=CAST(:r AS jsonb), "
        "ai_autoreply_confidence=:c, ai_autoreply_at=NOW(), ai_autoreply_status='pending' WHERE id=:id"),
        {"t": res["text"], "r": json.dumps(res), "c": res.get("confidence"), "id": email_id})
    db.commit()
    return res


@router.post("/ai/autoreply/{email_id}/generate")
def autoreply_generate(email_id: int, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """(Re)genereaza sugestia de reply pentru un email; reseteaza status la 'pending'."""
    res = _generate_and_store(db, email_id)
    return {"ok": True, "email_id": email_id, "ai_autoreply": res["text"],
            "ai_autoreply_confidence": res.get("confidence"),
            "ai_autoreply_status": "pending", "ai_autoreply_result": res}


@router.post("/ai/autoreply/{email_id}/preview-solved")
def autoreply_preview_solved(email_id: int, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Faza 2 — PREVIEW al reply-ului de INCHIDERE (kind='solved') pentru un email, ca sa validezi
    formularea. NU persista nimic si NU atinge sugestia de preluare (ai_autoreply)."""
    row = db.execute(text(
        "SELECT id, subject, from_address, from_name, body_text, body_html, conversation_id "
        "FROM emails WHERE id=:id"), {"id": email_id}).fetchone()
    if not row:
        raise HTTPException(404, "Email not found")
    res = A.generate_autoreply(dict(row._mapping), kind="solved")
    if not res.get("ok"):
        raise HTTPException(422, res.get("reason") or "Generare esuata")
    return {"ok": True, "email_id": email_id, "kind": "solved",
            "reply": res["text"], "confidence": res.get("confidence"), "model": res.get("model")}


@router.get("/ai/autoreply/solved-sample")
def autoreply_solved_sample(limit: int = Query(6, ge=1, le=12),
                            db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Faza 2 — esantion de PREVIEW-uri de reply de INCHIDERE pe emailuri reale deja SOLVED in CTS
    (primite, legate local), ca sa validezi mesajele inainte de a conecta trimiterea reala. NU persista
    si NU trimite nimic. Fiecare preview = un apel AI -> `limit` e plafonat (timeout worker)."""
    rows = db.execute(text(
        "SELECT e.id, e.subject, e.from_address, e.from_name, e.body_text, e.body_html, e.conversation_id "
        "FROM cts_ground_truth gt JOIN emails e ON e.id = gt.email_id "
        "WHERE gt.cts_status='solved' AND COALESCE(gt.cts_direction,'received')='received' "
        "ORDER BY gt.last_synced_at DESC NULLS LAST LIMIT :l"), {"l": limit}).fetchall()
    items = []
    for r in rows:
        m = dict(r._mapping)
        res = A.generate_autoreply(m, kind="solved")
        items.append({
            "email_id": m["id"], "subject": m.get("subject"), "from_address": m.get("from_address"),
            "ok": res.get("ok"), "reply": res.get("text") or None,
            "confidence": res.get("confidence"), "reason": res.get("reason"),
        })
    return {"count": len(items), "items": items,
            "note": "Preview reply de INCHIDERE (kind=solved). Nimic nu s-a trimis si nimic nu s-a salvat."}


@router.post("/ai/autoreply/dispatch-now")
def autoreply_dispatch_now(body: dict, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Ruleaza dispecerul (DRY-RUN) IN-SERVICE pentru niste email-uri, pe un trigger dat
    ('new_in_cts' | 'solved'). Util pt validare/ops — generarea AI e disponibila doar in proces.
    NU trimite nimic real (send_mode ramane dry_run); doar logheaza decizia in autoreply_send_log."""
    ids = body.get("ids") or []
    trigger = (body.get("trigger") or "new_in_cts").strip()
    if trigger not in ("new_in_cts", "solved"):
        raise HTTPException(400, "trigger invalid (new_in_cts | solved)")
    try:
        ids = [int(x) for x in ids][:100]
    except (TypeError, ValueError):
        raise HTTPException(400, "ids invalide (lista de intregi)")
    if not ids:
        raise HTTPException(400, "lipsesc ids")
    from app.services import autoreply_dispatch
    res = autoreply_dispatch.dispatch_for_ids(ids, trigger=trigger, force=bool(body.get("force")))
    return {"ok": True, **res}


@router.post("/ai/autoreply/{email_id}/accept")
def autoreply_accept(email_id: int, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Operatorul ACCEPTA sugestia (semnal pozitiv). NU trimite nimic — doar marcheaza + logheaza."""
    row = db.execute(text("SELECT ai_autoreply FROM emails WHERE id=:id"), {"id": email_id}).fetchone()
    if not row:
        raise HTTPException(404, "Email not found")
    suggested = row._mapping["ai_autoreply"]
    if not suggested:
        raise HTTPException(400, "Nu exista o sugestie de reply pentru acest email")
    reviewer = _reviewer(admin)
    db.execute(text(
        "INSERT INTO ai_autoreply_feedback(email_id, suggested_text, decision, decided_by) "
        "VALUES(:e, :t, 'accepted', :by)"),
        {"e": email_id, "t": suggested, "by": reviewer})
    db.execute(text("UPDATE emails SET ai_autoreply_status='accepted' WHERE id=:id"), {"id": email_id})
    db.commit()
    return {"ok": True, "email_id": email_id, "ai_autoreply_status": "accepted"}


@router.post("/ai/autoreply/{email_id}/reject")
def autoreply_reject(email_id: int, body: dict, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Operatorul RESPINGE sugestia + scrie un motiv (text liber). Alimenteaza fine-tuning-ul."""
    reason = (body.get("reason") or "").strip()
    if len(reason) < 3:
        raise HTTPException(400, "Motivul respingerii e obligatoriu (minim 3 caractere).")
    row = db.execute(text("SELECT ai_autoreply FROM emails WHERE id=:id"), {"id": email_id}).fetchone()
    if not row:
        raise HTTPException(404, "Email not found")
    suggested = row._mapping["ai_autoreply"]
    if not suggested:
        raise HTTPException(400, "Nu exista o sugestie de reply pentru acest email")
    reviewer = _reviewer(admin)
    db.execute(text(
        "INSERT INTO ai_autoreply_feedback(email_id, suggested_text, decision, reject_reason, decided_by) "
        "VALUES(:e, :t, 'rejected', :r, :by)"),
        {"e": email_id, "t": suggested, "r": reason[:2000], "by": reviewer})
    db.execute(text("UPDATE emails SET ai_autoreply_status='rejected' WHERE id=:id"), {"id": email_id})
    db.commit()
    return {"ok": True, "email_id": email_id, "ai_autoreply_status": "rejected"}


@router.get("/ai/autoreply/rejections")
def autoreply_rejections(limit: int = Query(200, ge=1, le=2000),
                         db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Lista reply-urilor RESPINSE + motiv (pentru fine-tuning / regenerarea promptului)."""
    rows = db.execute(text(
        "SELECT f.id, f.email_id, f.suggested_text, f.reject_reason, f.decided_by, "
        "to_char(f.created_at,'YYYY-MM-DD HH24:MI') AS created_at, "
        "e.subject, e.from_address "
        "FROM ai_autoreply_feedback f JOIN emails e ON e.id=f.email_id "
        "WHERE f.decision='rejected' ORDER BY f.id DESC LIMIT :l"), {"l": limit}).fetchall()
    total = db.execute(text(
        "SELECT count(*) FROM ai_autoreply_feedback WHERE decision='rejected'")).scalar()
    return {"total": total, "items": [dict(r._mapping) for r in rows]}


@router.delete("/ai/autoreply/feedback")
def autoreply_feedback_reset(db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Reset: sterge TOT feedback-ul (acceptari + respingeri). NU atinge promptul. Ireversibil."""
    n = db.execute(text("SELECT count(*) FROM ai_autoreply_feedback")).scalar() or 0
    db.execute(text("DELETE FROM ai_autoreply_feedback"))
    db.commit()
    return {"ok": True, "deleted": int(n)}


@router.get("/ai/autoreply/stats")
def autoreply_stats(db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    row = db.execute(text(
        "SELECT "
        "count(*) FILTER (WHERE ai_autoreply_status IS NOT NULL) AS total, "
        "count(*) FILTER (WHERE ai_autoreply_status='pending') AS pending, "
        "count(*) FILTER (WHERE ai_autoreply_status='accepted') AS accepted, "
        "count(*) FILTER (WHERE ai_autoreply_status='rejected') AS rejected, "
        "count(*) FILTER (WHERE ai_autoreply_confidence >= 0.85) AS high_conf, "
        "round(avg(ai_autoreply_confidence)::numeric, 2) AS avg_conf "
        "FROM emails")).fetchone()
    d = dict(row._mapping)
    decided = (d["accepted"] or 0) + (d["rejected"] or 0)
    d["accept_rate"] = round(100.0 * (d["accepted"] or 0) / decided, 1) if decided else None
    d["avg_confidence"] = float(d["avg_conf"]) if d.get("avg_conf") is not None else None
    d.pop("avg_conf", None)
    d["configured"] = iris_ai.is_configured()
    return d


@router.get("/ai/autoreply/dispatch-log")
def autoreply_dispatch_log(limit: int = Query(100, ge=1, le=1000),
                           db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Jurnalul deciziilor de auto-trimitere (Faza 1 = dry-run): ce S-AR fi trimis (would_send),
    ce s-a sarit din anti-spam (throttled) sau din eligibilitate/incredere (skipped_*). + contoare
    (total / ultimele 24h). In dry-run NU reflecta trimiteri reale — vezi coloana send_mode."""
    rows = db.execute(text(
        "SELECT l.id, l.email_id, l.recipient, l.trigger, l.outcome, l.reason, "
        "l.confidence, l.suggested_text, l.send_mode, "
        "to_char(l.created_at, 'YYYY-MM-DD HH24:MI') AS created_at, e.subject "
        "FROM autoreply_send_log l LEFT JOIN emails e ON e.id = l.email_id "
        "ORDER BY l.id DESC LIMIT :l"), {"l": limit}).fetchall()
    by_outcome = db.execute(text(
        "SELECT outcome, count(*) AS n, "
        "count(*) FILTER (WHERE created_at > now() - interval '24 hours') AS n_24h "
        "FROM autoreply_send_log GROUP BY outcome ORDER BY n DESC")).fetchall()
    total = db.execute(text("SELECT count(*) FROM autoreply_send_log")).scalar() or 0
    return {
        "total": int(total),
        "by_outcome": [dict(r._mapping) for r in by_outcome],
        "items": [dict(r._mapping) for r in rows],
        "note": ("DRY-RUN: 'would_send' = ELIGIBIL, dar NU s-a trimis nimic real. "
                 "trigger='new_in_cts' (preluare la intrare) / 'solved' (inchidere la solutionare)."),
    }


# ── Prompt editabil (single-prompt, mirror '/ai/priority/prompt' + versionare) ──

@router.get("/ai/autoreply/prompt")
def get_autoreply_prompt(db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Promptul curent de generare a sugestiei de reply (DB peste default-ul din cod)."""
    cur = A.load_prompt()
    return {"ok": True, "prompt": cur, "default": A.DEFAULT_PROMPT, "is_default": cur == A.DEFAULT_PROMPT}


@router.put("/ai/autoreply/prompt")
def put_autoreply_prompt(body: dict, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Salveaza promptul de sugestie reply + scrie o versiune in istoric."""
    new_text = (body.get("prompt") or "").strip()
    if len(new_text) < 30:
        raise HTTPException(400, "Prompt prea scurt (minim 30 caractere).")
    reviewer = _reviewer(admin)
    source = (body.get("source") or "manual").strip()[:20]
    db.execute(text(
        "INSERT INTO settings(key, value, description, updated_by, updated_at) "
        "VALUES(:k, CAST(:v AS jsonb), 'Prompt generare sugestie reply auto', :by, NOW()) "
        "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_by=:by, updated_at=NOW()"),
        {"k": A.PROMPT_KEY, "v": json.dumps(new_text), "by": reviewer})
    db.execute(text(
        "INSERT INTO ai_autoreply_prompt_versions(prompt_text, source, explicatie, based_on, created_by) "
        "VALUES(:t, :s, :e, :b, :by)"),
        {"t": new_text, "s": source, "e": body.get("explicatie"),
         "b": body.get("based_on"), "by": reviewer})
    db.commit()
    return {"ok": True, "note": "Prompt salvat."}


@router.get("/ai/autoreply/prompt/versions")
def get_autoreply_prompt_versions(limit: int = Query(50, ge=1, le=500),
                                  db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Istoricul versiunilor de prompt (pentru restaurare in UI)."""
    rows = db.execute(text(
        "SELECT id, prompt_text, source, explicatie, based_on, created_by, "
        "to_char(created_at,'YYYY-MM-DD HH24:MI') AS created_at, length(prompt_text) AS len "
        "FROM ai_autoreply_prompt_versions ORDER BY id DESC LIMIT :l"), {"l": limit}).fetchall()
    return {"items": [dict(r._mapping) for r in rows]}


_REGEN_SYSTEM = (
    "Esti un inginer de prompturi. Primesti PROMPTUL ACTUAL care genereaza sugestii de reply "
    "pentru suportul unei firme de transport (CargoTrack), plus o lista de sugestii RESPINSE de "
    "operatori, fiecare cu MOTIVUL respingerii (ex. 'prea sec', 'trebuia mai politicos', 'nu e din "
    "context'). Rescrie promptul ca sa incorporeze aceste corecturi (ton, politete, rabdare, lungime, "
    "context), pastrandu-i structura si regulile dure (nu inventa date/sume, nu jigni, raspuns scurt). "
    "Returneaza DOAR un JSON valid: {\"prompt\":\"<promptul imbunatatit complet>\","
    "\"explicatie\":\"<ce ai schimbat, pe scurt>\"}"
)


@router.post("/ai/autoreply/regenerate-prompt")
def autoreply_regenerate_prompt(db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Cere AI un prompt imbunatatit pe baza reply-urilor respinse + motivele lor.
    NU salveaza automat — intoarce sugestia pentru revizuire (userul confirma din UI)."""
    if not iris_ai.is_configured():
        raise HTTPException(400, "IRIS AI neconfigurat (lipseste IRIS_AI_KEY)")
    rej = db.execute(text(
        "SELECT f.suggested_text, f.reject_reason, e.subject "
        "FROM ai_autoreply_feedback f JOIN emails e ON e.id=f.email_id "
        "WHERE f.decision='rejected' ORDER BY f.id DESC LIMIT 40")).fetchall()
    if not rej:
        raise HTTPException(400, "Nu exista reply-uri respinse pe baza carora sa regenerez promptul")
    lines = ["PROMPTUL ACTUAL:\n" + A.load_prompt(), "\n\nSUGESTII RESPINSE (cu motiv):"]
    for i, r in enumerate(rej, 1):
        m = r._mapping
        lines.append("\n[" + str(i) + "] Subiect: " + (m["subject"] or "(gol)") +
                     "\nSugestie AI: " + (m["suggested_text"] or "").strip()[:400] +
                     "\nMotiv respingere: " + (m["reject_reason"] or "").strip())
    content = "\n".join(lines)
    res = iris_ai.run_prompt(_REGEN_SYSTEM, content, response_format="json",
                             model_hint="claude-sonnet-4-6", temperature=0.2,
                             max_tokens=2000, task="cargo360:autoreply_prompt_regen")
    if not res.get("ok"):
        raise HTTPException(502, "Regenerare esuata: " + str(res.get("error")))
    parsed = res.get("parsed") or {}
    suggested = parsed.get("prompt")
    if not (isinstance(suggested, str) and suggested.strip()):
        raise HTTPException(502, "AI nu a returnat un prompt valid")
    return {"ok": True, "suggested": suggested.strip(), "explicatie": parsed.get("explicatie"),
            "based_on": len(rej), "model": res.get("model"), "usage": res.get("usage")}


@router.get("/ai/autoreply/ai-enabled")
def autoreply_ai_get(admin=Depends(get_current_admin)):
    """Starea switch-ului de generare AI sugestii reply email (ambele task-uri)."""
    return {"ok": True, "enabled": A.autoreply_ai_status()}


@router.post("/ai/autoreply/ai-enabled/toggle")
def autoreply_ai_toggle(body: dict = None, admin=Depends(get_current_admin)):
    """START/STOP generarea AI a sugestiilor de reply (runtime, fara restart)."""
    body = body or {}
    enabled = bool(body.get("enabled"))
    by = _reviewer(admin)
    A.set_autoreply_ai(enabled, by=by)
    return {"ok": True, "enabled": enabled,
            "message": ("Sugestii reply AI pornite - emailurile noi primesc sugestie de reply (consuma AI)."
                        if enabled else
                        "Sugestii reply AI oprite - emailurile noi NU mai primesc sugestie (fara cost AI).")}
