"""Feedback clienți — dashboard statistici (T7).

Date agregate per campanie și KPI pentru echipa de marketing/suport:
- Statistici trimitere: trimise / deschise / rată răspuns
- Cine a deschis și cine a lăsat comentariu
- Scoruri medii KPI + ranking dinamic + evoluție lunară
"""
import logging
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import get_db
from app.api.v1.auth import get_current_admin

logger = logging.getLogger("mailguard.feedback_dashboard")
router = APIRouter()


@router.get("/feedback/dashboard")
def get_feedback_dashboard(
    campaign_id: int = None,
    months: int = 6,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    """Dashboard agregat feedback: statistici campanii + scoruri KPI + evoluție.

    Parametri opționali:
      - campaign_id: filtrează pe o singură campanie (None = toate)
      - months: fereastră evoluție (implicite 6 luni)
    """
    months = max(1, min(months, 24))

    # ── 1. Statistici per campanie ──────────────────────────────────────────
    camp_filter = "AND t.campaign_id = :cid" if campaign_id else ""
    camp_params = {"cid": campaign_id} if campaign_id else {}

    camp_stats = db.execute(text(f"""
        SELECT
            c.id AS campaign_id,
            c.name AS campaign_name,
            COUNT(t.id)                                          AS sent,
            COUNT(t.id) FILTER (WHERE t.sent_at IS NOT NULL)    AS sent_ok,
            COUNT(t.id) FILTER (WHERE t.send_error IS NOT NULL AND t.sent_at IS NULL) AS send_errors,
            COUNT(t.id) FILTER (WHERE t.opened_at IS NOT NULL)  AS opened,
            COUNT(t.id) FILTER (WHERE t.used_at IS NOT NULL)    AS responded,
            ROUND(
                COUNT(t.id) FILTER (WHERE t.opened_at IS NOT NULL)::numeric
                / NULLIF(COUNT(t.id) FILTER (WHERE t.sent_at IS NOT NULL), 0) * 100, 1
            )                                                    AS open_rate_pct,
            ROUND(
                COUNT(t.id) FILTER (WHERE t.used_at IS NOT NULL)::numeric
                / NULLIF(COUNT(t.id) FILTER (WHERE t.sent_at IS NOT NULL), 0) * 100, 1
            )                                                    AS response_rate_pct
        FROM feedback_campaigns c
        LEFT JOIN feedback_form_tokens t ON t.campaign_id = c.id
        WHERE 1=1 {camp_filter}
        GROUP BY c.id, c.name
        ORDER BY c.name ASC
    """), camp_params).fetchall()
    camp_stats = [dict(r._mapping) for r in camp_stats]

    # ── 2. Cine a deschis (cu dată + metodă) ───────────────────────────────
    opened_rows = db.execute(text(f"""
        SELECT
            t.campaign_id,
            c.id AS campaign_id_ref,
            c.name AS campaign_name,
            cl.id AS client_id,
            cl.name AS client_name,
            cl.emails->>0 AS client_email,
            t.month_key,
            t.opened_at,
            t.opened_via,
            t.used_at
        FROM feedback_form_tokens t
        JOIN feedback_campaigns c ON c.id = t.campaign_id
        JOIN clients cl ON cl.id = t.client_id
        WHERE t.opened_at IS NOT NULL {camp_filter}
        ORDER BY t.opened_at DESC
        LIMIT 200
    """), camp_params).fetchall()
    opened_list = [dict(r._mapping) for r in opened_rows]

    # ── 3. Comentarii (cu rating + text) ───────────────────────────────────
    comments_rows = db.execute(text(f"""
        SELECT
            r.campaign_id,
            cl.id AS client_id,
            cl.name AS client_name,
            k.name AS kpi_name,
            k.key AS kpi_key,
            r.rating,
            k.scale_max,
            r.comment,
            r.submitted_at
        FROM feedback_kpi_ratings r
        JOIN feedback_kpis k ON k.id = r.kpi_id
        JOIN clients cl ON cl.id = r.client_id
        WHERE r.comment IS NOT NULL AND trim(r.comment) <> '' {camp_filter}
        ORDER BY r.submitted_at DESC
        LIMIT 300
    """), camp_params).fetchall()
    comments_list = [dict(r._mapping) for r in comments_rows]

    # ── 4. Scoruri medii per KPI (toate campaniile sau filtrate) ───────────
    kpi_scores = db.execute(text(f"""
        SELECT
            k.id AS kpi_id,
            k.key AS kpi_key,
            k.name AS kpi_name,
            k.scale_max,
            COUNT(r.id)                          AS total_ratings,
            ROUND(AVG(r.rating)::numeric, 2)     AS avg_rating,
            ROUND(AVG(r.rating::numeric / k.scale_max * 100), 1) AS avg_pct
        FROM feedback_kpis k
        LEFT JOIN feedback_kpi_ratings r ON r.kpi_id = k.id {camp_filter.replace('t.campaign_id', 'r.campaign_id')}
        WHERE k.active = true
        GROUP BY k.id, k.key, k.name, k.scale_max
        ORDER BY avg_pct DESC NULLS LAST
    """), camp_params).fetchall()
    kpi_scores = [dict(r._mapping) for r in kpi_scores]

    # Ranking: poziție în ordinea avg_pct DESC
    for i, row in enumerate(kpi_scores):
        row["rank"] = i + 1

    # ── 5. Evoluție lunară scoruri KPI ─────────────────────────────────────
    evolution = db.execute(text(f"""
        SELECT
            k.id AS kpi_id,
            k.key AS kpi_key,
            k.name AS kpi_name,
            to_char(date_trunc('month', r.submitted_at), 'YYYY-MM') AS month_key,
            COUNT(r.id)                          AS count,
            ROUND(AVG(r.rating)::numeric, 2)     AS avg_rating,
            ROUND(AVG(r.rating::numeric / k.scale_max * 100), 1) AS avg_pct
        FROM feedback_kpi_ratings r
        JOIN feedback_kpis k ON k.id = r.kpi_id
        WHERE r.submitted_at >= date_trunc('month', now()) - (:months || ' months')::interval
          {camp_filter.replace('t.campaign_id', 'r.campaign_id')}
        GROUP BY k.id, k.key, k.name, date_trunc('month', r.submitted_at)
        ORDER BY k.key ASC, month_key ASC
    """), {**camp_params, "months": months}).fetchall()
    evolution = [dict(r._mapping) for r in evolution]

    # ── 6. Global summary ──────────────────────────────────────────────────
    totals = db.execute(text(f"""
        SELECT
            COUNT(t.id)                                         AS total_tokens,
            COUNT(t.id) FILTER (WHERE t.sent_at IS NOT NULL)   AS total_sent,
            COUNT(t.id) FILTER (WHERE t.opened_at IS NOT NULL) AS total_opened,
            COUNT(t.id) FILTER (WHERE t.used_at IS NOT NULL)   AS total_responded,
            COUNT(DISTINCT t.client_id)                        AS unique_clients
        FROM feedback_form_tokens t
        WHERE 1=1 {camp_filter}
    """), camp_params).fetchone()
    summary = dict(totals._mapping)

    return {
        "summary": summary,
        "campaign_stats": camp_stats,
        "opened_list": opened_list,
        "comments": comments_list,
        "kpi_scores": kpi_scores,
        "evolution": evolution,
        "filters": {"campaign_id": campaign_id, "months": months},
    }
