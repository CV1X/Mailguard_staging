"""One-shot re-ingest + rescore of emails from email_parser_db, bounded by date.

Run AFTER the email tables have been wiped. Pulls every source email with
received_at >= CUTOFF, inserts into mailguard.emails (status='pending'), then
runs the standard processing pipeline (current phishing + spam + NDR rules).

Usage:  venv/bin/python mg_reingest_since.py [YYYY-MM-DD]   (default 2026-06-01)
Idempotent: insert is ON CONFLICT(graph_message_id) DO NOTHING.
"""
import os
import sys

sys.path.insert(0, "/opt/iris-mailguard")

# load .env so the service modules see DB creds
for _line in open("/opt/iris-mailguard/.env", encoding="utf-8"):
    _line = _line.strip()
    if _line and not _line.startswith("#") and "=" in _line:
        _k, _v = _line.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip())

import psycopg2
import psycopg2.extras
from app.services import parser_email_op_reader as R
from app.services import process_email as P

CUTOFF = sys.argv[1] if len(sys.argv) > 1 else "2026-06-01"


def fetch_since(cutoff):
    """Same projection as the live reader, but date-bounded and unlimited."""
    with R._conn_parser() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT id::text AS parser_id, "messageId" AS message_id, "from" AS from_address,
                   from_name, "to" AS to_address, subject, body_text, body_html,
                   received_at, category AS parser_category, classification,
                   classification_confidence, flags, spam_score, processing_status,
                   is_read, created_at
            FROM emails
            WHERE received_at >= %s
            ORDER BY received_at ASC
        """, (cutoff,))
        return [dict(r) for r in cur.fetchall()]


def main():
    print(f"[reingest] cutoff = {CUTOFF}")

    # safety: refuse to run unless mailguard.emails was actually wiped
    with R._conn_mg() as conn:
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM emails")
        existing = cur.fetchone()[0]
    print(f"[reingest] mailguard.emails currently = {existing}")
    if existing > 0:
        print("[reingest] ABORT: emails table is not empty. Run the wipe first "
              "(or pass --force to re-ingest into a non-empty table).")
        if "--force" not in sys.argv:
            return 1

    rows = fetch_since(CUTOFF)
    print(f"[reingest] fetched from source (>= {CUTOFF}) = {len(rows)}")

    inserted = R.insert_into_cargo360(rows)
    print(f"[reingest] inserted (new pending) = {inserted}")

    total = {}
    rounds = 0
    while True:
        res = P.process_pending_batch(limit=500)
        n = res.get("processed", 0)
        for k, v in res.items():
            total[k] = total.get(k, 0) + v
        rounds += 1
        print(f"[reingest] batch {rounds}: {res}")
        if n == 0:
            break
        if rounds > 100:
            print("[reingest] stop: safety cap of 100 rounds reached")
            break

    print(f"[reingest] DONE totals = {total}")

    with R._conn_mg() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT status, count(*) FROM emails GROUP BY status ORDER BY count(*) DESC
        """)
        dist = cur.fetchall()
        cur.execute("SELECT count(*) FROM email_spam")
        spam_n = cur.fetchone()[0]
    print(f"[reingest] final status distribution = {dist}")
    print(f"[reingest] email_spam rows = {spam_n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
