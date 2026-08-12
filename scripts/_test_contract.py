import sys, json
sys.path.insert(0, "/opt/iris-mailguard")
from dotenv import load_dotenv
load_dotenv("/opt/iris-mailguard/.env")
import os, psycopg2
from app.api.v1 import documents as D

tid = int(sys.argv[1]) if len(sys.argv) > 1 else 9
conn = psycopg2.connect(dbname=os.environ["DB_NAME"], user=os.environ["DB_USER"],
                        password=os.environ["DB_PASSWORD"], host=os.environ.get("DB_HOST","127.0.0.1"),
                        port=os.environ.get("DB_PORT","5433"))
cur = conn.cursor()
cur.execute("SELECT name, sample_path, sample_mime, extract_fields, extract_prompt FROM document_types WHERE id=%s", (tid,))
name, spath, smime, fields, prompt = cur.fetchone()
cur.close(); conn.close()

text, method = D._doc_text(spath, smime or "")
print("TYPE #%s  %s" % (tid, name))
print("sample:", spath)
print("method:", method, "| raw_text_len:", len(text or ""))
clipped = D._clip_doc_text(text or "")
print("clipped_len:", len(clipped), "| tail_included:", len(text or "") > len(clipped))
print("--- tail of clipped (last 300 chars) ---")
print((clipped or "")[-300:])
system = D._build_doc_extract_system(prompt, fields)
data, model, err = D._extract_doc(system, text, tid, name)
print("--- EXTRACTION ---")
print("model:", model, "| err:", err)
print(json.dumps(data, ensure_ascii=False, indent=2))
