import sys
sys.path.insert(0, "/opt/iris-mailguard")
from dotenv import load_dotenv
load_dotenv("/opt/iris-mailguard/.env")
import os, psycopg2
from app.api.v1 import documents as D

tid = int(sys.argv[1])
conn = psycopg2.connect(dbname=os.environ["DB_NAME"], user=os.environ["DB_USER"],
                        password=os.environ["DB_PASSWORD"], host=os.environ.get("DB_HOST","127.0.0.1"),
                        port=os.environ.get("DB_PORT","5433"))
cur = conn.cursor()
cur.execute("SELECT sample_path, sample_mime FROM document_types WHERE id=%s", (tid,))
spath, smime = cur.fetchone(); cur.close(); conn.close()
text, method = D._doc_text(spath, smime or "")
print("method:", method, "len:", len(text or ""))
print("=========== HEAD (first 2600) ===========")
print((text or "")[:2600])
print("=========== TAIL (last 1200) ===========")
print((text or "")[-1200:])
