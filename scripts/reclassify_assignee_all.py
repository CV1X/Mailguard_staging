"""Reasigneaza pe UTILIZATOR emailurile non-NDR cu logica/promptul curent (OPS-2026-0131).
Resumable & background-safe. Oglinda lui reclassify_dept_all.py: assignarea nu are coloana
'pending' — folosim marker temporal ai_assignee_at IS NULL SAU < job_start. Sare emailurile
asignate MANUAL (ai_assignee_manual=TRUE).

    python -m scripts.reclassify_assignee_all --job-start 2026-06-29T10:00:00+00:00
    python -m scripts.reclassify_assignee_all --job-start ... --from-date 2026-06-01
    python -m scripts.reclassify_assignee_all --job-start ... --from-id 5000

Scrie progresul in logs/reclassify_assignee_status.json (GET /ai/assignee/reclassify/status).
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
from app.services import assignee_classifier as A
import signal

_STOP = {"v": False}


def _on_term(signum, frame):
    _STOP["v"] = True


signal.signal(signal.SIGTERM, _on_term)

LOG = "/opt/iris-mailguard/logs/reclassify_assignee_all.log"
STATUS = "/opt/iris-mailguard/logs/reclassify_assignee_status.json"


def log(m):
    line = datetime.now().strftime("%Y-%m-%d %H:%M:%S ") + m
    with open(LOG, "a") as f:
        f.write(line + "\n")


def _now():
    return datetime.now(timezone.utc).isoformat()


def write_status(d):
    tmp = STATUS + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f)
    os.replace(tmp, STATUS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job-start", required=True)
    ap.add_argument("--from-date", default=None)
    ap.add_argument("--from-id", type=int, default=None)
    args = ap.parse_args()

    conds = ["status <> 'ndr'", "(ai_assignee_manual IS NOT TRUE)",
             "(ai_assignee_at IS NULL OR ai_assignee_at < %(js)s)"]
    params = {"js": args.job_start}
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
    log(f"START scope={scope} job_start={args.job_start} total={total} pid={os.getpid()}")
    st = {"running": True, "scope": scope, "job_start": args.job_start, "total": total,
          "processed": 0, "assigned": 0, "unassigned": 0, "started_at": started,
          "updated_at": started, "finished_at": None, "pid": os.getpid()}
    write_status(st)

    i = assigned = unassigned = 0
    try:
        while True:
            if _STOP["v"]:
                st.update(processed=i, assigned=assigned, unassigned=unassigned, running=False,
                          canceled=True, updated_at=_now(), finished_at=_now())
                write_status(st)
                log(f"CANCELED scope={scope} processed={i}")
                return
            cur.execute(f"SELECT id, subject, from_address, from_name, conversation_id, received_at, "
                        f"body_text, body_html, ai_department FROM emails WHERE {where} "
                        f"ORDER BY received_at DESC LIMIT 100", params)
            rows = cur.fetchall()
            if not rows:
                break
            for r in rows:
                if _STOP["v"]:
                    break
                em = dict(r)
                try:
                    res = A.classify_assignee(em)
                except Exception as e:
                    log(f"classify error id={em['id']}: {e}")
                    res = None
                if res is not None:
                    cur.execute("UPDATE emails SET ai_assignee=%s, ai_assignee_result=%s::jsonb, "
                                "ai_assignee_at=NOW() WHERE id=%s AND ai_assignee_manual IS NOT TRUE",
                                (res.get("assignee_email"), psycopg2.extras.Json(res), em["id"]))
                    if res.get("assignee_email"):
                        assigned += 1
                    else:
                        unassigned += 1
                else:
                    cur.execute("UPDATE emails SET ai_assignee_at=NOW() WHERE id=%s", (em["id"],))
                    unassigned += 1
                i += 1
                if i % 10 == 0:
                    st.update(processed=i, assigned=assigned, unassigned=unassigned, updated_at=_now())
                    write_status(st)
                if i % 50 == 0:
                    log(f"progress {i}/{total} assigned={assigned} unassigned={unassigned}")
        st.update(processed=i, assigned=assigned, unassigned=unassigned, running=False,
                  updated_at=_now(), finished_at=_now())
        write_status(st)
        log(f"FINISHED scope={scope} processed={i} assigned={assigned} unassigned={unassigned}")
    except Exception as e:
        st.update(processed=i, assigned=assigned, unassigned=unassigned, running=False,
                  updated_at=_now(), finished_at=_now(), error=str(e))
        write_status(st)
        log(f"CRASH scope={scope} processed={i} err={e}")
        raise


if __name__ == "__main__":
    main()
