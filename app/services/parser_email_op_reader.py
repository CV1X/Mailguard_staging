"""v0.4.1 — Reader from parser-email-op DB (Option C parallel mode).
Reads new emails from existing parser-email-op `emails` table and copies to
mailguard.emails with status='pending' for our own processing pipeline.
Zero credential sharing — uses cargo360 PG user with SELECT access to email_parser_db.
"""
import json
import logging
from typing import List, Dict, Any
import psycopg2
import psycopg2.extras

from app.config import get_settings

logger = logging.getLogger("mailguard.reader")
settings = get_settings()


def _conn_parser():
    """Connect to email_parser_db using cargo360 credentials (SELECT-only)."""
    return psycopg2.connect(
        host=settings.db_host, port=settings.db_port,
        dbname='email_parser_db', user=settings.db_user, password=settings.db_password,
    )


def _conn_mg():
    """Connect to cargo360 DB (full access)."""
    return psycopg2.connect(
        host=settings.db_host, port=settings.db_port,
        dbname=settings.db_name, user=settings.db_user, password=settings.db_password,
    )


def get_last_synced_message_id() -> str:
    """Returns most recently synced messageId, or empty string if none."""
    with _conn_mg() as conn:
        cur = conn.cursor()
        cur.execute("SELECT value FROM settings WHERE key='last_synced_parser_message_id'")
        row = cur.fetchone()
        return (row[0] if row else '""').strip('"')


def set_last_synced_message_id(message_id: str):
    with _conn_mg() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO settings(key, value, description)
            VALUES('last_synced_parser_message_id', %s::jsonb, 'Tracker pentru sync incremental din parser-email-op')
            ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()
        """, (f'"{message_id}"',))
        conn.commit()


def _build_email_headers(em: dict) -> dict:
    """Construieste blocul de headere din câmpurile disponibile în parser_db.

    Câmpurile List-Unsubscribe, Authentication-Results full, DKIM-Signature
    nu sunt disponibile în parser_db (parser-email-op nu le persistă).
    Vor fi adăugate automat când mail-parser va fi extins să salveze headerele brute.
    Câmpul email_headers este gata să le primească.
    """
    headers: Dict[str, Any] = {}

    # Flags din parser — conțin rezultate SPF/DKIM ca text procesate
    # Ex: ["SPF softfail", "DKIM pass", "Clean Content Boost: ..."]
    flags = em.get('flags') or []
    if flags:
        headers['authentication_flags'] = list(flags)

    # Message-ID (dacă disponibil din parser)
    if em.get('message_id'):
        headers['message_id'] = em['message_id']

    return headers


def fetch_new_emails_from_parser(limit: int = 100) -> List[Dict[str, Any]]:
    """Fetch emails from parser-email-op not yet in mailguard.emails (by messageId)."""
    with _conn_parser() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT id::text AS parser_id, "messageId" AS message_id, "from" AS from_address,
                   from_name, "to" AS to_address, subject, body_text, body_html,
                   received_at, category AS parser_category, classification,
                   classification_confidence, flags, spam_score, processing_status,
                   is_read, created_at
            FROM emails
            WHERE "messageId" NOT IN (
                SELECT graph_message_id FROM dblink('dbname=cargo360',
                    'SELECT graph_message_id FROM emails')
                AS t(graph_message_id varchar)
            )
            ORDER BY received_at DESC
            LIMIT %s
        """, (limit,))
        # NOTE: dblink not available by default; fallback inline-style below
        # Replaced: just fetch all + dedup in Python
        return [dict(r) for r in cur.fetchall()]


def fetch_new_emails_simple(limit: int = 100, since_days: int = None,
                            from_date: str = None, to_date: str = None) -> List[Dict[str, Any]]:
    """Simple version: fetch latest N emails from parser, dedup in Python.

    since_days (optional): daca e setat, intoarce TOATE emailurile din parser
    primite in ultimele N zile (fereastra de data, fara cap de count) — folosit
    pentru reimport controlat. Implicit None => comportamentul incremental normal
    al cron-ului (latest limit*5, dedup, taie la limit).
    from_date (optional, 'YYYY-MM-DD'): boundary CALENDARISTIC — intoarce TOT din parser
    cu received_at >= from_date (00:00). Prioritar fata de since_days. Folosit de butonul
    de reset+reimport ca sa aduca exact zilele cerute (ex. de la 17.06 incoace).
    to_date (optional, 'YYYY-MM-DD'): limita superioara (inclusiv) — received_at < to_date+1."""
    with _conn_mg() as conn_mg:
        cur_mg = conn_mg.cursor()
        cur_mg.execute("SELECT graph_message_id FROM emails ORDER BY received_at DESC LIMIT 10000")
        already_synced = {row[0] for row in cur_mg.fetchall()}

    base_cols = (
        'SELECT id::text AS parser_id, "messageId" AS message_id, "from" AS from_address, '
        'from_name, "to" AS to_address, subject, body_text, body_html, '
        'received_at, category AS parser_category, classification, '
        'classification_confidence, flags, spam_score, processing_status, '
        'is_read, created_at FROM emails ')
    window = since_days is not None or from_date is not None
    with _conn_parser() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        if from_date is not None:
            if to_date is not None:
                # interval calendaristic [from_date, to_date] inclusiv
                cur.execute(
                    base_cols + "WHERE received_at >= %s::date AND received_at < %s::date + INTERVAL '1 day' "
                    "ORDER BY received_at DESC",
                    (str(from_date), str(to_date)))
            else:
                # boundary calendaristic: tot din ziua from_date incoace (reimport one-shot)
                cur.execute(
                    base_cols + "WHERE received_at >= %s::date ORDER BY received_at DESC",
                    (str(from_date),))
        elif since_days is not None:
            # fereastra de data: ia TOT din ultimele N zile (reimport one-shot)
            cur.execute(
                base_cols + "WHERE received_at >= now() - (%s || ' days')::interval "
                "ORDER BY received_at DESC", (int(since_days),))
        else:
            cur.execute(
                base_cols + "ORDER BY received_at DESC LIMIT %s",
                (limit * 5,))  # over-fetch to account for dedup
        rows = [dict(r) for r in cur.fetchall()]

    new_rows = [r for r in rows if r['message_id'] not in already_synced]
    return new_rows if window else new_rows[:limit]


def insert_into_cargo360(emails: List[Dict[str, Any]]) -> int:
    """Insert fetched emails into mailguard.emails with status='pending'."""
    if not emails:
        return 0
    inserted = 0
    with _conn_mg() as conn:
        cur = conn.cursor()
        for em in emails:
            try:
                email_headers = _build_email_headers(em)
                cur.execute("""
                    INSERT INTO emails(
                        graph_message_id, subject, from_address, from_name,
                        to_addresses, received_at, body_text, body_html,
                        raw_graph_payload, email_headers, status, fetched_at
                    ) VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s::jsonb, %s::jsonb, 'pending', NOW())
                    ON CONFLICT (graph_message_id) DO NOTHING
                """, (
                    em['message_id'], em.get('subject'), em.get('from_address'),
                    em.get('from_name'), f'["{em.get("to_address","")}"]',
                    em.get('received_at'), em.get('body_text'), em.get('body_html'),
                    json.dumps({"source": "parser-email-op", "parser_id": str(em.get('parser_id', ''))}),
                    json.dumps(email_headers),
                ))
                if cur.rowcount > 0:
                    inserted += 1
            except Exception as e:
                logger.warning(f"Skipping email {em.get('message_id')}: {e}")
        conn.commit()
    return inserted


def sync_attachments(limit: int = None) -> Dict[str, int]:
    """Copy attachment records from parser-email-op for cargo360 emails that have
    none yet. Linked via emails.raw_graph_payload->>'parser_id' = source emails.id
    (= source attachments.emailMessageId). Idempotent (skips emails already populated)."""
    with _conn_mg() as conn_mg:
        cur = conn_mg.cursor()
        q = ("SELECT id, raw_graph_payload->>'parser_id' AS pid FROM emails "
             "WHERE raw_graph_payload->>'parser_id' IS NOT NULL "
             "AND NOT EXISTS (SELECT 1 FROM attachments a WHERE a.email_id = emails.id)")
        if limit:
            q += " LIMIT %s"
            cur.execute(q, (limit,))
        else:
            cur.execute(q)
        rows = cur.fetchall()
    pid_to_mgid = {str(pid): mid for (mid, pid) in rows if pid}
    if not pid_to_mgid:
        return {"emails": 0, "attachments": 0}
    pids = list(pid_to_mgid.keys())

    with _conn_parser() as conn_src:
        curs = conn_src.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        curs.execute(
            'SELECT "emailMessageId"::text AS eid, id::text AS aid, filename, '
            '"contentType" AS ctype, path FROM attachments WHERE "emailMessageId"::text = ANY(%s)',
            (pids,))
        src = curs.fetchall()

    inserted, touched = 0, set()
    with _conn_mg() as conn_mg:
        cur = conn_mg.cursor()
        for a in src:
            mgid = pid_to_mgid.get(a['eid'])
            if not mgid:
                continue
            cur.execute("""
                INSERT INTO attachments(email_id, graph_attachment_id, name, content_type, storage_path, is_suspicious)
                VALUES(%s, %s, %s, %s, %s, FALSE)
            """, (mgid, a['aid'], a['filename'], a['ctype'], a['path']))
            inserted += 1
            touched.add(mgid)
        if touched:
            cur.execute("UPDATE emails SET has_attachments=TRUE WHERE id = ANY(%s)", (list(touched),))
        conn_mg.commit()
    logger.info(f"sync_attachments: emails={len(touched)} attachments={inserted}")
    return {"emails": len(touched), "attachments": inserted}


def sync_run(limit: int = 100, since_days: int = None, from_date: str = None,
             to_date: str = None) -> Dict[str, int]:
    """Top-level: fetch + insert + copy attachments. Returns {fetched, inserted, attachments}.

    since_days (optional): reimport one-shot al ultimelor N zile (ignora limit).
    from_date (optional, 'YYYY-MM-DD'): reimport calendaristic de la data X incoace.
    to_date (optional, 'YYYY-MM-DD'): limita superioara inclusiv (interval [from_date, to_date])."""
    emails = fetch_new_emails_simple(limit=limit, since_days=since_days, from_date=from_date,
                                     to_date=to_date)
    inserted = insert_into_cargo360(emails)
    att = {"attachments": 0}
    try:
        att = sync_attachments()
    except Exception as e:
        logger.warning(f"sync_attachments failed: {e}")
    logger.info(f"sync: fetched={len(emails)} inserted={inserted} attachments={att.get('attachments', 0)}")
    return {"fetched": len(emails), "inserted": inserted, "attachments": att.get("attachments", 0)}
