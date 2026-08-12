#!/usr/bin/env python3
"""Backfill interaction_analysis pentru clienții eligibili care lipsesc.

Utilizare:
  python3 scripts/backfill_interaction_analysis.py [--n 200] [--dry-run]
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

logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","name":"%(name)s","msg":%(message)r}',
    stream=sys.stdout,
)
logger = logging.getLogger("backfill_ia")

import psycopg2
from app.config import get_settings
from app.services.interaction_analyzer import process_batch


def get_clients_missing_ia(n: int = 200, window_days: int = 90) -> list:
    """Clienți cu ≥2 interacțiuni în 90 zile dar fără interaction_analysis."""
    s = get_settings()
    conn = psycopg2.connect(host=s.db_host, port=s.db_port, dbname=s.db_name, user=s.db_user, password=s.db_password)
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
                  AND NOT EXISTS (
                    SELECT 1 FROM interaction_analysis ia
                    WHERE ia.client_id = c.id AND ia.occurred_at >= {cutoff}
                  )
                ORDER BY c.id
                LIMIT %s
            """, (n,))
            return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=200)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    logger.info("Caut clienți fără interaction_analysis (max %d)...", args.n)
    client_ids = get_clients_missing_ia(n=args.n)
    logger.info("Găsiți %d clienți de backfillat.", len(client_ids))

    if not client_ids:
        print(json.dumps({"status": "nothing_to_do"}))
        return

    if args.dry_run:
        print(json.dumps({"dry_run": True, "would_process": len(client_ids), "client_ids": client_ids[:10]}))
        return

    s = get_settings()
    conn = psycopg2.connect(host=s.db_host, port=s.db_port, dbname=s.db_name, user=s.db_user, password=s.db_password)
    conn.autocommit = False
    try:
        cur = conn.cursor()
        # Procesăm în batch-uri de 50 pentru a evita timeout-uri IRIS
        CHUNK = 50
        total_stats = {"emails_analyzed": 0, "calls_analyzed": 0, "skipped": 0, "errors": 0}
        for i in range(0, len(client_ids), CHUNK):
            chunk = client_ids[i:i + CHUNK]
            logger.info("Procesez chunk %d-%d / %d...", i + 1, i + len(chunk), len(client_ids))
            stats = process_batch(cur, conn, client_ids=chunk, limit_emails=500, limit_calls=200)
            for k in total_stats:
                total_stats[k] += stats.get(k, 0)
            logger.info("Chunk done: %s", stats)

        print(json.dumps(total_stats))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
