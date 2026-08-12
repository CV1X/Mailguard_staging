#!/usr/bin/env python3
"""Re-rulează snapshot-ul pentru clienții cu iris_reasoning gol sau iris_fallback în luna dată."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

import json
import logging
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","name":"%(name)s","msg":%(message)r}',
    stream=sys.stdout,
)
logger = logging.getLogger("fix_missing_reasoning")

import psycopg2
from app.config import get_settings
from app.services.satisfaction_snapshot import run_monthly_snapshot


def get_clients_missing_reasoning(month_key: str) -> list:
    settings = get_settings()
    conn = psycopg2.connect(
        host=settings.db_host, port=settings.db_port,
        dbname=settings.db_name, user=settings.db_user, password=settings.db_password,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT s.client_id
                FROM client_satisfaction_snapshots s
                JOIN clients c ON c.id = s.client_id
                WHERE s.month_key = %s
                  AND c.satisfaction_exclude = FALSE
                  AND (
                    s.breakdown->>'iris_reasoning' IS NULL
                    OR s.breakdown->>'iris_reasoning' = ''
                    OR s.breakdown->>'scoring_mode' = 'iris_fallback'
                  )
                ORDER BY s.client_id
            """, (month_key,))
            return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def main():
    month_key = sys.argv[1] if len(sys.argv) > 1 else datetime.now(timezone.utc).strftime("%Y-%m")
    logger.info("Fix reasoning gol pentru luna %s...", month_key)
    client_ids = get_clients_missing_reasoning(month_key)
    logger.info("Clienți de re-procesat: %d", len(client_ids))
    if not client_ids:
        print(json.dumps({"status": "nothing_to_fix"}))
        return
    result = run_monthly_snapshot(
        month_key=month_key,
        dry_run=False,
        force=True,
        client_ids=client_ids,
    )
    print(json.dumps(result, ensure_ascii=False))
    if result.get("errors", 0) > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
