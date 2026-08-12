#!/usr/bin/env python3
"""Reprocesare eșantion satisfacție — selectează primii N clienți cu ≥2 interacțiuni în 90 zile.

Utilizare:
  python3 scripts/satisfaction_recalibrate_sample.py              # 200 clienți, luna curentă, force
  python3 scripts/satisfaction_recalibrate_sample.py --n 100      # 100 clienți
  python3 scripts/satisfaction_recalibrate_sample.py --dry-run    # fără persistență
  python3 scripts/satisfaction_recalibrate_sample.py 2026-07      # lună specifică
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# dotenv ÎNAINTE de orice import din app/ (lru_cache pe get_settings)
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

import argparse
import json
import logging
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","name":"%(name)s","msg":%(message)r}',
    stream=sys.stdout,
)
logger = logging.getLogger("recalibrate_sample")

import psycopg2
from psycopg2.extras import RealDictCursor
from app.config import get_settings
from app.services.satisfaction_snapshot import run_monthly_snapshot


def get_clients_with_interactions(n: int = 200, window_days: int = 90) -> list:
    """Selectează primii N clienți activi cu ≥2 interacțiuni (email sau apel) în ultimele window_days zile."""
    settings = get_settings()
    # Construiește DSN direct (psycopg2 pur, fără SQLAlchemy)
    dsn_kwargs = dict(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password,
    )
    conn = psycopg2.connect(**dsn_kwargs)
    try:
        with conn.cursor() as cur:
            cutoff = f"NOW() - INTERVAL '{window_days} days'"
            cur.execute(f"""
                SELECT c.id
                FROM clients c
                WHERE c.is_active = TRUE AND c.satisfaction_exclude = FALSE
                  AND (
                    (SELECT COUNT(*) FROM emails e WHERE e.client_id = c.id AND e.received_at >= {cutoff}) +
                    (SELECT COUNT(*) FROM calls ca WHERE ca.client_id = c.id AND ca.started_at >= {cutoff})
                  ) >= 2
                ORDER BY c.id
                LIMIT %s
            """, (n,))
            rows = cur.fetchall()
            return [r[0] for r in rows]
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Reprocesare eșantion satisfacție clienți")
    parser.add_argument("month", nargs="?", default=None, help="YYYY-MM (default: luna curentă)")
    parser.add_argument("--n", type=int, default=200, help="Număr clienți de procesat (default: 200)")
    parser.add_argument("--dry-run", action="store_true", help="Calculează fără a persista")
    args = parser.parse_args()

    month_key = args.month
    if month_key and len(month_key) != 7:
        print(f"Format invalid: {month_key!r} — folosiți YYYY-MM", file=sys.stderr)
        sys.exit(2)

    logger.info("Selectez clienți cu ≥2 interacțiuni în 90 zile (max %d)...", args.n)
    client_ids = get_clients_with_interactions(n=args.n)
    logger.info("Găsiți %d clienți eligibili.", len(client_ids))

    if not client_ids:
        print(json.dumps({"error": "no_eligible_clients"}))
        sys.exit(1)

    result = run_monthly_snapshot(
        month_key=month_key,
        dry_run=args.dry_run,
        force=True,  # suprascrie snapshot-urile existente
        client_ids=client_ids,
    )
    print(json.dumps(result, ensure_ascii=False))

    if result.get("errors", 0) > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
