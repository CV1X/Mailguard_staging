#!/usr/bin/env python3
"""Runner pentru snapshot lunar satisfacție clienți.

Utilizare:
  python3 scripts/satisfaction_monthly.py               # luna curentă
  python3 scripts/satisfaction_monthly.py 2026-06       # lună specifică
  python3 scripts/satisfaction_monthly.py --dry-run     # calculează, fără persistență
  python3 scripts/satisfaction_monthly.py 2026-06 --dry-run

Programare recomandată (crontab pe mailguard-staging):
  0 3 1 * * /opt/iris-mailguard/venv/bin/python3 /opt/iris-mailguard/scripts/satisfaction_monthly.py >> /opt/iris-mailguard/storage/logs/satisfaction_monthly.log 2>&1
"""
import sys
import os

# Adaugă rădăcina proiectului în path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import argparse
import json
import logging

logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","name":"%(name)s","msg":%(message)r}',
    stream=sys.stdout,
)

from app.services.satisfaction_snapshot import run_monthly_snapshot


def main():
    parser = argparse.ArgumentParser(description="Snapshot lunar satisfacție clienți")
    parser.add_argument("month", nargs="?", default=None, help="YYYY-MM (default: luna curentă)")
    parser.add_argument("--dry-run", action="store_true", help="Calculează fără a persista")
    parser.add_argument("--force", action="store_true", help="Recalculează snapshot-urile existente ale lunii (ON CONFLICT DO UPDATE)")
    args = parser.parse_args()

    month_key = args.month
    if month_key and len(month_key) != 7:
        print(f"Format invalid: {month_key!r} — folosiți YYYY-MM", file=sys.stderr)
        sys.exit(2)

    result = run_monthly_snapshot(month_key=month_key, dry_run=args.dry_run, force=args.force)
    print(json.dumps(result, ensure_ascii=False))

    if result.get("errors", 0) > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
