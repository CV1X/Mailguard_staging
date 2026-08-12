"""Feedback clienți — formular public (T4).

Pagina publică de feedback, accesată printr-un link tokenizat (fără cont,
fără JWT). Clientul vede KPI-urile campaniei sale și trimite un rating
(stele) + comentariu opțional per KPI. Tokenul e neghicibil (32 bytes
random, urlsafe), expiră după un interval fix și e invalidat imediat după
submit (one-time).

Endpoint-uri publice — NU folosesc `get_current_admin`. Fiecare validare
de token verifică explicit expirarea și starea "folosit" înainte de a
expune orice date.
"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel, Field

from app.database import get_db

logger = logging.getLogger("mailguard.feedback_public")
router = APIRouter()

# GIF transparent 1x1 — folosit ca pixel de tracking pentru deschideri (T5).
_TRACKING_PIXEL = bytes.fromhex(
    "47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024c01003b"
)


def _mark_opened_if_first(db: Session, token: str, via: str) -> None:
    """Marchează opened_at/opened_via DOAR la primul semnal (pixel sau click,
    oricare vine primul) — nu suprascrie un semnal deja înregistrat. Best-effort:
    un token invalid/expirat aici nu trebuie să dea eroare vizibilă (pixelul se
    încarcă mereu, formularul își face propria validare separat)."""
    db.execute(text("""
        UPDATE feedback_form_tokens SET opened_at = now(), opened_via = :via
        WHERE token = :token AND opened_at IS NULL
    """), {"token": token, "via": via})
    db.commit()


def _get_active_google_review_url(db: Session) -> Optional[str]:
    """Întoarce linkul Google Reviews configurat, DACĂ e activ — necondiționat
    de rating-ul trimis (fără gating pe sentiment, vezi CLAUDE.md notă T6)."""
    row = db.execute(text("""
        SELECT review_url FROM feedback_google_config WHERE active = true ORDER BY id LIMIT 1
    """)).fetchone()
    return row._mapping["review_url"] if row else None


class RatingInput(BaseModel):
    kpi_id: int
    rating: int = Field(..., ge=1)
    comment: Optional[str] = Field(None, max_length=2000)


class FeedbackSubmit(BaseModel):
    ratings: list[RatingInput] = Field(..., min_length=1)


def _get_valid_token_or_404(db: Session, token: str) -> dict:
    row = db.execute(text("""
        SELECT t.id, t.campaign_id, t.client_id, t.month_key, t.expires_at, t.used_at
        FROM feedback_form_tokens t
        WHERE t.token = :token
    """), {"token": token}).fetchone()
    if not row:
        raise HTTPException(404, "Link invalid")
    info = dict(row._mapping)
    if info["used_at"] is not None:
        raise HTTPException(410, "Acest link a fost deja folosit")
    expired = db.execute(text("SELECT :exp < now()"), {"exp": info["expires_at"]}).scalar()
    if expired:
        raise HTTPException(410, "Acest link a expirat")
    return info


@router.get("/public/feedback/pixel/{token}.gif")
def feedback_open_pixel(token: str, db: Session = Depends(get_db)):
    """Pixel invizibil de tracking — marchează 'deschis' dacă emailul e afișat cu
    imagini activate. Orientativ: multe cliente de mail blochează imaginile implicit,
    clic pe link (mai jos) e semnalul sigur. Întoarce mereu imaginea, indiferent de
    starea tokenului — un pixel care ar da 404 ar putea rupe randarea în unele cliente."""
    try:
        _mark_opened_if_first(db, token, "pixel")
    except Exception:
        logger.exception("Eroare marcare pixel deschidere token_prefix=%s", (token or "")[:8])
    return Response(content=_TRACKING_PIXEL, media_type="image/gif")


@router.get("/public/feedback/{token}")
def get_feedback_form(token: str, db: Session = Depends(get_db)):
    """Validează tokenul și întoarce doar ce e necesar pentru formular:
    numele clientului + KPI-urile active ale campaniei. Fără alte date."""
    info = _get_valid_token_or_404(db, token)
    _mark_opened_if_first(db, token, "click")

    campaign = db.execute(text("""
        SELECT id, name, kpi_ids FROM feedback_campaigns WHERE id = :id
    """), {"id": info["campaign_id"]}).fetchone()
    if not campaign:
        raise HTTPException(404, "Campania nu mai există")
    campaign = dict(campaign._mapping)

    client = db.execute(text("SELECT id, name FROM clients WHERE id = :id"),
                         {"id": info["client_id"]}).fetchone()
    client_name = client._mapping["name"] if client else None

    kpi_ids = campaign["kpi_ids"] or []
    if not kpi_ids:
        kpis = []
    else:
        rows = db.execute(text("""
            SELECT id, key, name, description, scale_max, comment_enabled, comment_label
            FROM feedback_kpis WHERE id = ANY(:ids) AND active = true ORDER BY sort_order ASC
        """), {"ids": kpi_ids}).fetchall()
        kpis = [dict(r._mapping) for r in rows]

    return {
        "client_name": client_name,
        "campaign_name": campaign["name"],
        "kpis": kpis,
    }


@router.post("/public/feedback/{token}")
def submit_feedback_form(token: str, body: FeedbackSubmit, db: Session = Depends(get_db)):
    """Salvează rating-urile trimise, legate de client + campanie, apoi
    invalidează tokenul (one-time) — indiferent de rezultat, un token nu
    poate fi refolosit după acest apel."""
    info = _get_valid_token_or_404(db, token)

    campaign = db.execute(text("SELECT kpi_ids FROM feedback_campaigns WHERE id = :id"),
                           {"id": info["campaign_id"]}).fetchone()
    kpi_ids = campaign._mapping["kpi_ids"] or [] if campaign else []
    scale_by_kpi = {}
    if kpi_ids:
        rows = db.execute(text("SELECT id, scale_max FROM feedback_kpis WHERE id = ANY(:ids)"),
                           {"ids": kpi_ids}).fetchall()
        scale_by_kpi = {r._mapping["id"]: r._mapping["scale_max"] for r in rows}

    for r in body.ratings:
        if r.kpi_id not in scale_by_kpi:
            raise HTTPException(400, f"KPI {r.kpi_id} nu face parte din această campanie")
        if r.rating > scale_by_kpi[r.kpi_id]:
            raise HTTPException(400, f"Rating invalid pentru KPI {r.kpi_id} (max {scale_by_kpi[r.kpi_id]})")

    for r in body.ratings:
        db.execute(text("""
            INSERT INTO feedback_kpi_ratings (kpi_id, client_id, campaign_id, rating, comment)
            VALUES (:kpi_id, :client_id, :campaign_id, :rating, :comment)
        """), {"kpi_id": r.kpi_id, "client_id": info["client_id"],
                "campaign_id": info["campaign_id"], "rating": r.rating, "comment": r.comment})

    db.execute(text("UPDATE feedback_form_tokens SET used_at = now() WHERE id = :id"),
               {"id": info["id"]})
    db.commit()
    return {"ok": True, "google_review_url": _get_active_google_review_url(db)}
