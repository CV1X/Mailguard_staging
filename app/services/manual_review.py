"""Verificare manuală (learning / QA retrospectiv).

Job zilnic agățat pe cron-ul existent de 5 min (via /process/run-now).
Self-gated + idempotent: face pick-ul pentru ZIUA DE IERI exact o dată/zi.

Model: NU reține nimic de la CTS — fluxul existent rămâne neatins. Doar
eșantionează ~pct% din mailurile CLEAN de ieri pentru verificare umană:
  - TOATE necunoscutele reale (ai_category='necunoscut' AND ai_status='done');
  - dacă sunt sub target, completează cu random din cele deja încadrate.
Corecțiile umane intră în ai_category_corrections -> pagina "Emailuri încadrate
greșit" + "Regenerează prompturi (AI)".
"""
import json
import math
import logging

from sqlalchemy import text

from app.database import SessionLocal

logger = logging.getLogger("mailguard.manual_review")

CATS = ["informatie", "sesizare", "reclamatie", "necunoscut"]

# Expeditori INTERNI / proprii — mailurile trimise DE NOI spre clienți și adresele interne
# (@cargotrack.ro, ex. registru.release@, iris@, diana.perticas@) NU intră la verificarea manuală
# (learning vrea doar corespondența PRIMITĂ de la clienți). Acoperă și subdomeniile (x.cargotrack.ro).
INTERNAL_SENDER_DOMAINS = ("cargotrack.ro", "nordlogistics.eu", "deltacargo.eu")


def internal_sender_not_sql(col="from_address"):
    """Predicat SQL: TRUE dacă expeditorul NU e pe un domeniu intern. COALESCE → un from_address
    NULL nu e considerat intern (rămâne în eșantion)."""
    parts = []
    for d in INTERNAL_SENDER_DOMAINS:
        parts.append("lower(COALESCE(%s,'')) LIKE '%%@%s'" % (col, d))
        parts.append("lower(COALESCE(%s,'')) LIKE '%%.%s'" % (col, d))
    return "NOT (" + " OR ".join(parts) + ")"


def get_setting(db, key, default=None):
    r = db.execute(text("SELECT value FROM settings WHERE key=:k"), {"k": key}).fetchone()
    return r[0] if r else default


def set_setting(db, key, value):
    db.execute(text(
        "INSERT INTO settings(key, value, updated_by, updated_at) "
        "VALUES(:k, CAST(:v AS jsonb), 'iris', NOW()) "
        "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, "
        "updated_by='iris', updated_at=NOW()"),
        {"k": key, "v": json.dumps(value)})


def pick_for_range(start_date, end_date):
    """Esantioneaza ~pct% din mailurile CLEAN cu received_at (Europe/Bucharest) in
    [start_date, end_date] pentru verificare manuala (fine-tuning). NU e gated pe last_batch
    — ruleaza la cerere (folosit de reset+reimport pe zilele reimportate, mai putin azi).
    start_date/end_date: 'YYYY-MM-DD'. Aceeasi logica ca daily: unknown-first + random fill."""
    db = SessionLocal()
    try:
        pct = get_setting(db, "manual_review.pct", 20) or 20
        _intf = "AND " + internal_sender_not_sql()
        clean_total = db.execute(text(
            "SELECT count(*) FROM emails WHERE status='clean' "
            "AND (received_at AT TIME ZONE 'Europe/Bucharest')::date BETWEEN :a AND :b"),
            {"a": start_date, "b": end_date}).scalar() or 0
        target = math.ceil(pct / 100.0 * clean_total)
        r1 = db.execute(text(
            "UPDATE emails SET manual_review_state='pending', manual_review_reason='unknown', "
            "manual_review_batch=:b, manual_review_picked_at=NOW() "
            "WHERE status='clean' AND (received_at AT TIME ZONE 'Europe/Bucharest')::date BETWEEN :a AND :b "
            "AND ai_category='necunoscut' AND ai_status='done' AND manual_review_state IS NULL " + _intf),
            {"a": start_date, "b": end_date})
        n_unknown = r1.rowcount or 0
        need = max(0, target - n_unknown)
        n_random = 0
        if need > 0:
            r2 = db.execute(text(
                "UPDATE emails SET manual_review_state='pending', manual_review_reason='random', "
                "manual_review_batch=:b, manual_review_picked_at=NOW() "
                "WHERE id IN (SELECT id FROM emails "
                "  WHERE status='clean' AND (received_at AT TIME ZONE 'Europe/Bucharest')::date BETWEEN :a AND :b "
                "  AND ai_status='done' AND ai_category IS NOT NULL AND ai_category NOT IN ('necunoscut','') "
                "  AND manual_review_state IS NULL " + _intf + " ORDER BY random() LIMIT :n)"),
                {"a": start_date, "b": end_date, "n": need})
            n_random = r2.rowcount or 0
        db.commit()
        res = {"range": [str(start_date), str(end_date)], "clean_total": clean_total,
               "target": target, "picked_unknown": n_unknown, "picked_random": n_random}
        logger.info("manual_review pick_for_range: %s", res)
        return res
    finally:
        db.close()


def run_daily_pick_if_due():
    """Best-effort: face pick-ul pentru ieri dacă modulul e pornit și nu a rulat azi."""
    db = SessionLocal()
    try:
        enabled = get_setting(db, "manual_review.enabled", True)
        if not enabled:
            return {"skipped": "disabled"}

        ydate = db.execute(text(
            "SELECT ((now() AT TIME ZONE 'Europe/Bucharest')::date - 1)")).scalar()
        yiso = ydate.isoformat()

        last = get_setting(db, "manual_review.last_batch", None)
        if last and str(last) == yiso:
            return {"skipped": "already_done", "batch": yiso}

        pct = get_setting(db, "manual_review.pct", 20) or 20
        _intf = "AND " + internal_sender_not_sql()
        clean_total = db.execute(text(
            "SELECT count(*) FROM emails WHERE status='clean' "
            "AND (received_at AT TIME ZONE 'Europe/Bucharest')::date = :y"),
            {"y": ydate}).scalar() or 0
        target = math.ceil(pct / 100.0 * clean_total)

        # 1) toate necunoscutele reale (AI a rulat și a zis necunoscut)
        r1 = db.execute(text(
            "UPDATE emails SET manual_review_state='pending', manual_review_reason='unknown', "
            "manual_review_batch=:y, manual_review_picked_at=NOW() "
            "WHERE status='clean' AND (received_at AT TIME ZONE 'Europe/Bucharest')::date=:y "
            "AND ai_category='necunoscut' AND ai_status='done' "
            "AND manual_review_state IS NULL " + _intf),
            {"y": ydate})
        n_unknown = r1.rowcount or 0

        # 2) completare random din cele deja încadrate, până la target
        need = max(0, target - n_unknown)
        n_random = 0
        if need > 0:
            r2 = db.execute(text(
                "UPDATE emails SET manual_review_state='pending', manual_review_reason='random', "
                "manual_review_batch=:y, manual_review_picked_at=NOW() "
                "WHERE id IN ("
                "  SELECT id FROM emails "
                "  WHERE status='clean' AND (received_at AT TIME ZONE 'Europe/Bucharest')::date=:y "
                "  AND ai_status='done' AND ai_category IS NOT NULL "
                "  AND ai_category NOT IN ('necunoscut','') "
                "  AND manual_review_state IS NULL " + _intf + " "
                "  ORDER BY random() LIMIT :n)"),
                {"y": ydate, "n": need})
            n_random = r2.rowcount or 0

        set_setting(db, "manual_review.last_batch", yiso)
        db.commit()
        res = {"batch": yiso, "clean_total": clean_total, "target": target,
               "picked_unknown": n_unknown, "picked_random": n_random}
        logger.info("manual_review pick: %s", res)
        return res
    except Exception as e:  # pragma: no cover - never break the caller
        db.rollback()
        logger.warning("run_daily_pick_if_due failed: %s", e)
        return {"error": str(e)}
    finally:
        db.close()
