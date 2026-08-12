#!/usr/bin/env python3
"""Reclasifică emailurile din divergențele CTS (departament, fără suport_1) cu prompturile noi."""
import sys, json, time
sys.path.insert(0, '/opt/iris-mailguard')

import os
from pathlib import Path
env_file = Path('/opt/iris-mailguard/.env')
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, _, v = line.partition('=')
            os.environ.setdefault(k.strip(), v.strip())

from app.database import SessionLocal
from sqlalchemy import text
from app.services import department_classifier

db = SessionLocal()

rows = db.execute(text(
    "SELECT e.id, e.ai_department AS dept_before, gt.cts_department AS cts_dept "
    "FROM cts_ground_truth gt JOIN emails e ON e.id=gt.email_id "
    "WHERE COALESCE(gt.cts_direction,'received')='received' "
    "  AND gt.cts_department IS NOT NULL AND e.ai_department IS NOT NULL "
    "  AND gt.cts_department <> e.ai_department "
    "  AND e.ai_department <> 'suport_1' AND gt.cts_department <> 'suport_1' "
    "ORDER BY gt.changed_at DESC NULLS LAST, gt.email_id DESC"
)).fetchall()

total = len(rows)
print(f"Total divergente: {total}", flush=True)

# Verificam ca modulul exista
print(f"Classifier: {department_classifier.__file__}", flush=True)

corrected = unchanged = errors = 0
from collections import Counter
pairs = Counter()

for i, r in enumerate(rows, 1):
    m = dict(r._mapping)
    email_row = db.execute(text(
        "SELECT id, subject, from_address, from_name, body_text, body_html, conversation_id, received_at "
        "FROM emails WHERE id=:id"
    ), {"id": m['id']}).fetchone()
    if not email_row:
        errors += 1
        print(f"  [{i}/{total}] id={m['id']} — NOT FOUND", flush=True)
        continue

    email = dict(email_row._mapping)
    res = department_classifier.classify_department(email, force_fresh=True)
    if not res:
        errors += 1
        print(f"  [{i}/{total}] id={m['id']} — EROARE clasificare", flush=True)
        continue

    dept_after = res.get('department')
    db.execute(text(
        "UPDATE emails SET ai_department=:d, ai_department_result=CAST(:r AS jsonb), "
        "ai_department_at=NOW() WHERE id=:id"
    ), {"d": dept_after, "r": json.dumps(res), "id": m['id']})
    db.commit()

    correct = (dept_after == m['cts_dept'])
    if correct:
        corrected += 1
    else:
        unchanged += 1
    status = "CORECTAT" if correct else "INCA GRESIT"
    pairs[f"{m['dept_before']}->{dept_after} (CTS={m['cts_dept']})"] += 1
    print(f"  [{i}/{total}] id={m['id']} {m['dept_before']}->{dept_after} (CTS={m['cts_dept']}) — {status}", flush=True)
    time.sleep(0.05)

db.close()
print(f"\n=== REZULTAT FINAL ===", flush=True)
print(f"Total: {total} | Corectate: {corrected} ({corrected*100//total if total else 0}%) | Inca gresite: {unchanged} | Erori: {errors}", flush=True)
print("\nTop perechi:", flush=True)
for pair, n in pairs.most_common(15):
    print(f"  {n}x {pair}", flush=True)
