import sys, json
sys.path.insert(0, "/opt/iris-mailguard")
from dotenv import load_dotenv
load_dotenv("/opt/iris-mailguard/.env")
import os, psycopg2
from app.database import SessionLocal
from app.api.v1 import documents as D
from sqlalchemy import text

n = int(sys.argv[1]) if len(sys.argv) > 1 else 8
db = SessionLocal()
rows = [dict(r._mapping) for r in db.execute(text(
    "SELECT a.id, a.email_id, a.name, a.content_type, a.storage_path "
    "FROM attachments a JOIN emails e ON e.id=a.email_id "
    "WHERE e.received_at::date = CURRENT_DATE ORDER BY a.id DESC LIMIT :n"), {"n": n}).fetchall()]
print("Testez %d atasamente de azi\n" % len(rows))
for att in rows:
    try:
        st = D._process_attachment(db, att, force=True)
    except Exception as e:
        st = "EXC: " + str(e)[:200]
    r = db.execute(text("SELECT category, detected_type, confidence, status, method, "
                        "left(confidence_reason,80) AS reason, data FROM document_extractions "
                        "WHERE attachment_id=:a"), {"a": att["id"]}).fetchone()
    m = dict(r._mapping) if r else {}
    print("att#%-5s %-40s mime=%s" % (att["id"], (att["name"] or "")[:40], att["content_type"]))
    print("   -> status=%s cat=%s tip=%s conf=%s method=%s" % (
        m.get("status"), m.get("category"), m.get("detected_type"), m.get("confidence"), m.get("method")))
    if m.get("reason"):
        print("      reason:", m["reason"])
    if m.get("data") and m["data"] != {}:
        print("      data:", json.dumps(m["data"], ensure_ascii=False)[:300])
    print()
db.close()
