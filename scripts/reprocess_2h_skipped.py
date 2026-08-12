"""One-shot: reclassify emails from last 2h that have ai_status='skipped'.

Runs advance_one_clean() per email — covers category + department + priority + assignee.
Safe to re-run (idempotent: emails already 'done' are excluded by the WHERE).

Usage: python -m scripts.reprocess_2h_skipped [--hours N]
"""
import os, sys, argparse

for line in open("/opt/iris-mailguard/.env", encoding="utf-8"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

sys.path.insert(0, "/opt/iris-mailguard")

import psycopg2, psycopg2.extras
from app.config import get_settings
from app.services import process_email


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=2.0,
                    help="Look back N hours (default 2)")
    args = ap.parse_args()

    s = get_settings()
    conn = psycopg2.connect(host=s.db_host, port=s.db_port, dbname=s.db_name,
                            user=s.db_user, password=s.db_password)
    conn.autocommit = True
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT id, subject, from_address
        FROM emails
        WHERE ai_status = 'skipped'
          AND received_at >= NOW() - INTERVAL '%s hours'
          AND status NOT IN ('ndr', 'spam', 'quarantined')
        ORDER BY received_at DESC
    """, (args.hours,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    print(f"[reprocess_2h] Found {len(rows)} emails (ai_status=skipped, last {args.hours}h)")
    ok = err = skipped = 0

    for row in rows:
        eid = row["id"]
        subj = (row.get("subject") or "")[:60]
        try:
            res = process_email.advance_one_clean(eid)
            status = res.get("status", "?")
            cat = res.get("category", "-")
            if status == "skipped":
                skipped += 1
            else:
                ok += 1
            print(f"  [{eid}] {status} cat={cat!r:20s} | {subj}")
        except Exception as e:
            err += 1
            print(f"  [{eid}] ERROR: {e} | {subj}")

    print(f"\n[reprocess_2h] Done: ok={ok} skipped={skipped} err={err} / total={len(rows)}")


if __name__ == "__main__":
    main()
