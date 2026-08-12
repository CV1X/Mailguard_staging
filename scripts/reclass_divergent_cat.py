"""One-shot: reclasifica CATEGORIA pe toate divergentele MG<->CTS (mailuri PRIMITE),
ocolind curated-cache (force_fresh=True) ca prompturile curente sa se aplice efectiv.

Tinteste DOAR emailurile unde ai_category <> cts_category (deci fara regresie pe cele
deja corecte). Update emails.ai_category/ai_result. Log vechi->nou + daca acum coincide cu CTS.

Rulare (ca root, env-ul serviciului):
    sudo /opt/iris-mailguard/venv/bin/python -m scripts.reclass_divergent_cat
"""
import os, sys
for line in open("/opt/iris-mailguard/.env", encoding="utf-8"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip())
sys.path.insert(0, "/opt/iris-mailguard")
import psycopg2, psycopg2.extras
from app.config import get_settings
from app.services import category_classifier as C

SEL = """
SELECT e.id, e.subject, e.from_address, e.from_name, e.body_text, e.body_html,
       e.ai_category AS old_cat, gt.cts_category AS cts_cat
FROM cts_ground_truth gt JOIN emails e ON e.id = gt.email_id
WHERE COALESCE(gt.cts_direction,'received') = 'received'
  AND gt.cts_category IS NOT NULL AND e.ai_category IS NOT NULL
  AND gt.cts_category <> e.ai_category
  AND gt.cts_category IN ('informatie','sesizare','reclamatie','necunoscut')
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
    print("DIVERGENTE de reclasificat: %d" % total, flush=True)
    for r in rows:
        em = dict(r)
        old_cat, cts_cat = em.pop("old_cat"), em.pop("cts_cat")
        try:
            res = C.classify_category(em, force_fresh=True)
        except Exception as e:
            res = None
            print("  #%s EROARE: %s" % (em["id"], e), flush=True)
        if not res:
            errors += 1
            continue
        new_cat = res["category"]
        cur.execute("UPDATE emails SET ai_category=%s, ai_result=%s::jsonb, "
                    "ai_status='done', ai_processed_at=NOW() WHERE id=%s",
                    (new_cat, psycopg2.extras.Json(res), em["id"]))
        if new_cat != old_cat:
            changed += 1
        if new_cat == cts_cat:
            fixed += 1
        flag = "OK->CTS" if new_cat == cts_cat else ("schimbat" if new_cat != old_cat else "neschimbat")
        print("  #%s %s: %s -> %s (CTS=%s) [%s]" % (
            em["id"], (em.get("from_address") or "")[:28], old_cat, new_cat, cts_cat, flag), flush=True)
    print("REZUMAT: total=%d corectate_la_CTS=%d schimbate=%d erori=%d" % (
        total, fixed, changed, errors), flush=True)


if __name__ == "__main__":
    main()
