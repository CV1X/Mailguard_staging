"""Feedback clienți — reguli generale de frecvență & opt-out (T3).

Protejează clientul de suprasolicitare, transversal peste TOATE campaniile
(T2): reține ultima trimitere per client, exclude automat clienții care au
primit feedback în ultimele X luni (fereastră configurabilă), și respectă
opt-out-ul manual. Expune `apply_frequency_rules()`, apelată de T2 în
`_apply_global_exclusions`, ÎNAINTE de selecția random.
"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel, Field

from app.database import get_db
from app.api.v1.auth import get_current_admin

logger = logging.getLogger("mailguard.feedback_frequency")
router = APIRouter()

_DEFAULT_MIN_MONTHS = 6


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class FrequencySettings(BaseModel):
    min_months_between_sends: int = Field(..., ge=1, le=36)


# ── Helper — apelat din T2 ────────────────────────────────────────────────────

def get_min_months_between_sends(db: Session) -> int:
    row = db.execute(text("SELECT value FROM settings WHERE key = 'feedback.frequency'")).fetchone()
    if not row:
        return _DEFAULT_MIN_MONTHS
    return int(row._mapping["value"].get("min_months_between_sends", _DEFAULT_MIN_MONTHS))


def apply_frequency_rules(db: Session, candidates: list[dict]) -> tuple[list[dict], list[dict]]:
    """Filtrează candidații (deja trecuți prin criteriile segmentului) prin regulile
    globale de frecvență: opt-out manual + fereastră minimă față de ultima trimitere.

    Regulă transversală — nu ține cont de campanie, doar de client. Returnează
    (eligibili, exclusi_cu_motiv), în aceeași formă folosită de T2.
    """
    if not candidates:
        return [], []

    min_months = get_min_months_between_sends(db)
    ids = [c["id"] for c in candidates]
    rows = db.execute(text("""
        SELECT id, feedback_opt_out, feedback_last_sent_at,
               (feedback_last_sent_at IS NOT NULL
                AND feedback_last_sent_at > now() - (:min_months || ' months')::interval) AS within_window
        FROM clients
        WHERE id = ANY(:ids)
    """), {"ids": ids, "min_months": min_months}).fetchall()
    by_id = {r._mapping["id"]: r._mapping for r in rows}

    eligible, excluded = [], []
    for c in candidates:
        info = by_id.get(c["id"])
        if info and info["feedback_opt_out"]:
            excluded.append({**c, "excluded_reason": "opt_out"})
        elif info and info["within_window"]:
            excluded.append({**c, "excluded_reason": "frecventa_recenta"})
        else:
            eligible.append(c)
    return eligible, excluded


def mark_feedback_sent(db: Session, client_ids: list[int]) -> None:
    """Actualizează 'ultima trimitere' pentru clienții efectiv selectați într-un eșantion.

    Apelat din T2 la run-sample — DOAR pentru clienții selectați (nu pentru toți candidații),
    ca fereastra de frecvență să reflecte trimiterea reală, nu doar eligibilitatea.
    """
    if not client_ids:
        return
    db.execute(text("""
        UPDATE clients SET feedback_last_sent_at = now()
        WHERE id = ANY(:ids)
    """), {"ids": client_ids})


# ── Endpoints — setare fereastră globală ──────────────────────────────────────

@router.get("/feedback/frequency-settings")
def get_frequency_settings(db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    return {"min_months_between_sends": get_min_months_between_sends(db)}


@router.put("/feedback/frequency-settings")
def update_frequency_settings(body: FrequencySettings, db: Session = Depends(get_db),
                               admin=Depends(get_current_admin)):
    db.execute(text("""
        INSERT INTO settings (key, value)
        VALUES ('feedback.frequency', jsonb_build_object('min_months_between_sends', :m))
        ON CONFLICT (key) DO UPDATE SET value = jsonb_build_object('min_months_between_sends', :m)
    """), {"m": body.min_months_between_sends})
    db.commit()
    return {"min_months_between_sends": body.min_months_between_sends}


# ── Endpoints — opt-out per client ────────────────────────────────────────────

@router.get("/feedback/opt-outs")
def list_opt_outs(db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    rows = db.execute(text("""
        SELECT id, name, feedback_opt_out, feedback_last_sent_at
        FROM clients WHERE feedback_opt_out = true ORDER BY name ASC
    """)).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/clients/{client_id}/feedback-opt-out")
def set_client_opt_out(client_id: int, opt_out: bool, db: Session = Depends(get_db),
                        admin=Depends(get_current_admin)):
    db.execute(text("UPDATE clients SET feedback_opt_out = :v WHERE id = :id"),
               {"v": opt_out, "id": client_id})
    db.commit()
    row = db.execute(text("SELECT id, name, feedback_opt_out FROM clients WHERE id = :id"),
                      {"id": client_id}).fetchone()
    return dict(row._mapping) if row else {"id": client_id, "feedback_opt_out": opt_out}
