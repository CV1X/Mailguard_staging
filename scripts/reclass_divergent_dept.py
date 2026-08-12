"""One-shot: reincadreaza DEPARTAMENTUL pe toate divergentele MG<->CTS (mailuri PRIMITE),
ocolind curated-cache (force_fresh=True) + base-head de-biasat. Sare emailurile corectate
MANUAL (ai_department_manual=TRUE). Tinteste DOAR divergentele -> fara regresie pe corecte.

Rulare: sudo /opt/iris-mailguard/venv/bin/python /opt/iris-mailguard/scripts/reclass_divergent_dept.py
"""
import os, sys
for line in open("/opt/iris-mailguard/.env", encoding="utf-8"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip())
sys.path.insert(0, "/opt/iris-mailguard")
import psycopg2, psycopg2.extras
from app.config import get_settings
from app.services import department_classifier as D

SEL = """
SELECT e.id, e.subject, e.from_address, e.from_name, e.body_text, e.body_html,
       e.ai_department AS old_dep, gt.cts_department AS cts_dep
FROM cts_ground_truth gt JOIN emails e ON e.id = gt.email_id
WHERE COALESCE(gt.cts_direction,'received') = 'received'
  AND gt.cts_department IS NOT NULL AND e.ai_department IS NOT NULL
  AND gt.cts_department <> e.ai_department
  AND (e.ai_department_manual IS NOT TRUE)
ORDER BY e.id
"""


def main():
    s = get_settings()
    conn = psycopg2.connect(host=s.db_host, port=s.db_port, dbname=s.db_name,
                            user=s.db_user, password=s.db_password)
    conn.autocommit = True
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(SEL)
    rows = cur.fetchall()
    total = len(rows)
    fixed = changed = errors = 0
    print("DIVERGENTE dept de reclasificat: %d" % total, flush=True)
    for r in rows:
        em = dict(r)
        old_dep, cts_dep = em.pop("old_dep"), em.pop("cts_dep")
        try:
            res = D.classify_department(em, force_fresh=True)
        except Exception as e:
            res = None
            print("  #%s EROARE: %s" % (em["id"], e), flush=True)
        if not res or not res.get("department"):
            errors += 1
            continue
        new_dep = res["department"]
        cur.execute("UPDATE emails SET ai_department=%s, ai_department_result=%s::jsonb, "
                    "ai_department_at=NOW() WHERE id=%s",
                    (new_dep, psycopg2.extras.Json(res), em["id"]))
        if new_dep != old_dep:
            changed += 1
        if new_dep == cts_dep:
            fixed += 1
        flag = "OK->CTS" if new_dep == cts_dep else ("schimbat" if new_dep != old_dep else "neschimbat")
        print("  #%s: %s -> %s (CTS=%s) [%s]" % (em["id"], old_dep, new_dep, cts_dep, flag), flush=True)
    print("REZUMAT: total=%d corectate_la_CTS=%d schimbate=%d erori=%d" % (
        total, fixed, changed, errors), flush=True)


if __name__ == "__main__":
    main()
