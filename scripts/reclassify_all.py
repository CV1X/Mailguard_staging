"""Reclassify non-NDR emails with the current category prompts. Resumable & background-safe.

Processes only ai_status='pending' (the /start endpoint resets the chosen range to
'pending' once before launching), so a restart simply continues where it left off.

Run modes (the email rows are selected by the endpoint via the reset; this script just
drains pending, optionally narrowed to the same range so two ranges don't interfere):
    python -m scripts.reclassify_all                 # all pending (default)
    python -m scripts.reclassify_all --from-date 2026-06-01
    python -m scripts.reclassify_all --from-id 5000

Writes live progress to logs/reclassify_status.json (read by GET /ai/category/reclassify/status)
and a human log to logs/reclassify_all.log. Fire-and-forget: spawned detached by the API so
closing the UI never stops it.
"""
import os, sys, json, argparse
for line in open("/opt/iris-mailguard/.env", encoding="utf-8"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip())
sys.path.insert(0, "/opt/iris-mailguard")
import psycopg2, psycopg2.extras
from datetime import datetime, timezone
from app.config import get_settings
from app.services import category_classifier as C
import signal

_STOP = {"v": False}


def _on_term(signum, frame):
    _STOP["v"] = True


signal.signal(signal.SIGTERM, _on_term)

LOG = "/opt/iris-mailguard/logs/reclassify_all.log"
STATUS = "/opt/iris-mailguard/logs/reclassify_status.json"


def log(m):
    line = datetime.now().strftime("%Y-%m-%d %H:%M:%S ") + m
    with open(LOG, "a") as f:
        f.write(line + "\n")


def _now():
    return datetime.now(timezone.utc).isoformat()


def write_status(d):
    # atomic-ish write so the status endpoint never reads a half file
    tmp = STATUS + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f)
    os.replace(tmp, STATUS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-date", default=None)
    ap.add_argument("--from-id", type=int, default=None)
    ap.add_argument("--fresh", action="store_true",
                    help="ocoleste curated-cache (force_fresh) ca prompturile curente sa se aplice")
    args = ap.parse_args()

    # WHERE narrowing identical to the API's _range_where (keeps concurrent ranges isolated)
    conds = ["status <> 'ndr'", "ai_status='pending'"]
    params = {}
    scope = "all"
    if args.from_date:
        conds.append("received_at >= %(fd)s"); params["fd"] = args.from_date; scope = "date:" + args.from_date
    if args.from_id is not None:
        conds.append("id >= %(fid)s"); params["fid"] = args.from_id; scope = "id:" + str(args.from_id)
    where = " AND ".join(conds)

    s = get_settings()
    conn = psycopg2.connect(host=s.db_host, port=s.db_port, dbname=s.db_name,
                            user=s.db_user, password=s.db_password)
    conn.autocommit = True
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute(f"SELECT count(*) AS n FROM emails WHERE {where}", params)
    total = cur.fetchone()["n"]
    started = _now()
    log(f"START scope={scope} pending={total} pid={os.getpid()}")
    st = {"running": True, "scope": scope, "total": total, "processed": 0,
          "done": 0, "errors": 0, "started_at": started, "updated_at": started,
          "finished_at": None, "pid": os.getpid()}
    write_status(st)

    i = done = errors = 0
    try:
        while True:
            if _STOP["v"]:
                st.update(processed=i, done=done, errors=errors, running=False, canceled=True, updated_at=_now(), finished_at=_now())
                write_status(st)
                log(f"CANCELED scope={scope} processed={i} done={done} errors={errors}")
                return
            cur.execute(f"SELECT id, subject, from_address, from_name, body_text, body_html "
                        f"FROM emails WHERE {where} ORDER BY received_at DESC LIMIT 100", params)
            rows = cur.fetchall()
            if not rows:
                break
            for r in rows:
                if _STOP["v"]:
                    break
                em = dict(r)
                try:
                    res = C.classify_category(em, force_fresh=args.fresh)
                except Exception:
                    res = None
                if res:
                    cur.execute("UPDATE emails SET ai_category=%s, ai_result=%s::jsonb, "
                                "ai_status='done', ai_processed_at=NOW() WHERE id=%s",
                                (res["category"], psycopg2.extras.Json(res), em["id"]))
                    done += 1
                else:
                    cur.execute("UPDATE emails SET ai_status='error', ai_processed_at=NOW() WHERE id=%s",
                                (em["id"],))
                    errors += 1
                i += 1
                # heartbeat + live progress every 10 emails (status) / 50 (log)
                if i % 10 == 0:
                    st.update(processed=i, done=done, errors=errors, updated_at=_now())
                    write_status(st)
                if i % 50 == 0:
                    log(f"progress {i}/{total} done={done} errors={errors}")
        st.update(processed=i, done=done, errors=errors, running=False,
                  updated_at=_now(), finished_at=_now())
        write_status(st)
        log(f"FINISHED scope={scope} processed={i} done={done} errors={errors}")
    except Exception as e:
        st.update(processed=i, done=done, errors=errors, running=False,
                  updated_at=_now(), finished_at=_now(), error=str(e))
        write_status(st)
        log(f"CRASH scope={scope} processed={i} err={e}")
        raise


if __name__ == "__main__":
    main()
