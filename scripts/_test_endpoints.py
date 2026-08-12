import sys, json
sys.path.insert(0, "/opt/iris-mailguard")
from dotenv import load_dotenv
load_dotenv("/opt/iris-mailguard/.env")
from app.database import SessionLocal
from app.api.v1 import documents as D
from sqlalchemy import text

admin = {"username": "cristian-raul.covaci"}
db = SessionLocal()

# 1) list extractions (today, fara neidentificate)
r = D.list_extractions(scope="today", include_skipped=False, db=db, admin=admin)
print("LIST counts:", r["counts"], "| items:", len(r["items"]))
sample = [it for it in r["items"] if it["status"] == "extracted"]
print("primul extracted:", sample[0]["att_name"] if sample else None,
      "->", sample[0]["detected_type"] if sample else None)

# 2) detail pe un extracted
if sample:
    exid = sample[0]["id"]
    d = D.get_extraction(exid, db=db, admin=admin)["item"]
    print("DETAIL id=%s status=%s type_fields=%d data_keys=%s" % (
        exid, d["status"], len(d.get("type_fields") or []), list((d.get("data") or {}).keys())[:4]))

    # 3) PUT: editez un camp + marchez reviewed
    data = dict(d.get("data") or {})
    if data:
        k0 = list(data.keys())[0]
        data[k0] = "EDIT_TEST_123"
    D.update_extraction(exid, {"data": data}, db=db, admin=admin)
    chk = db.execute(text("SELECT reviewed, data FROM document_extractions WHERE id=:i"), {"i": exid}).fetchone()
    print("dupa PUT: reviewed=%s data[%s]=%s" % (chk[0], k0 if data else "-", (chk[1] or {}).get(k0) if data else None))

    # 4) drain('new') NU trebuie sa atinga randul reviewed (e deja cu rand) -> verific ramane EDIT
    D._drain_doc_extractions("today", limit=200)
    chk2 = db.execute(text("SELECT reviewed, data FROM document_extractions WHERE id=:i"), {"i": exid}).fetchone()
    print("dupa re-drain: reviewed=%s data[%s]=%s (trebuie sa ramana EDIT_TEST_123)" % (
        chk2[0], k0 if data else "-", (chk2[1] or {}).get(k0) if data else None))

db.close()
print("OK")
