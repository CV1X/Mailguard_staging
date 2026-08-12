#!/usr/bin/env python3
"""Reclasifică emailurile rămase sesizare (AI) vs informatie (CTS) cu promptul actualizat."""
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
from app.services import category_classifier

db = SessionLocal()

rows = db.execute(text(
    "SELECT e.id, e.ai_category AS cat_before, gt.cts_category AS cts_cat "
    "FROM cts_ground_truth gt JOIN emails e ON e.id=gt.email_id "
    "WHERE COALESCE(gt.cts_direction,'received')='received' "
    "  AND gt.cts_category = 'informatie' "
    "  AND e.ai_category = 'sesizare' "
    "  AND gt.cts_category <> e.ai_category "
    "ORDER BY gt.changed_at DESC NULLS LAST"
)).fetchall()

total = len(rows)
print(f"De reclasificat: {total}", flush=True)
prompts = category_classifier.load_prompts()

corrected = unchanged = errors = 0
for i, r in enumerate(rows, 1):
    m = dict(r._mapping)
    email_row = db.execute(text(
        "SELECT id, subject, from_address, from_name, body_text, body_html, conversation_id, received_at "
        "FROM emails WHERE id=:id"
    ), {"id": m['id']}).fetchone()
    if not email_row:
        errors += 1
        continue
    res = category_classifier.classify_category(dict(email_row._mapping), prompts=prompts, force_fresh=True)
    if not res:
        errors += 1
        continue
    cat_after = res.get('category')
    db.execute(text(
        "UPDATE emails SET ai_category=:c, ai_result=CAST(:r AS jsonb), "
        "ai_status='done', ai_processed_at=NOW() WHERE id=:id"
    ), {"c": cat_after, "r": json.dumps(res), "id": m['id']})
    db.commit()
    correct = (cat_after == m['cts_cat'])
    if correct:
        corrected += 1
    else:
        unchanged += 1
    status = "CORECTAT" if correct else "INCA GRESIT"
    print(f"  [{i}/{total}] id={m['id']} sesizare->{cat_after} (CTS=informatie) — {status}", flush=True)
    time.sleep(0.05)

db.close()
print(f"\nCorectat: {corrected}/{total} ({corrected*100//total if total else 0}%)", flush=True)
print(f"Inca gresit: {unchanged}, Erori: {errors}", flush=True)
