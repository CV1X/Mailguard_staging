#!/usr/bin/env python3
"""Reclasifică emailurile din divergențele CTS (categorie) cu prompturile noi.
Raportează câte s-au corectat față de adevărul CTS."""
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
import json as _json

db = SessionLocal()

# 1. Colectăm emailurile divergente cu adevărul CTS
rows = db.execute(text(
    "SELECT e.id, e.subject, e.from_address, e.ai_category AS cat_before, "
    "gt.cts_category AS cts_cat, "
    "LEFT(COALESCE(e.body_text, e.body_html, ''), 200) AS snippet "
    "FROM cts_ground_truth gt JOIN emails e ON e.id=gt.email_id "
    "WHERE COALESCE(gt.cts_direction,'received')='received' "
    "  AND gt.cts_category IS NOT NULL AND e.ai_category IS NOT NULL "
    "  AND gt.cts_category <> e.ai_category "
    "  AND gt.cts_category IN ('informatie','sesizare','reclamatie','necunoscut') "
    "ORDER BY gt.changed_at DESC NULLS LAST, gt.email_id DESC"
)).fetchall()

total = len(rows)
print(f"Total divergente de reclasificat: {total}", flush=True)

# Încărcăm prompturile noi din DB
prompts = category_classifier.load_prompts()
print(f"Prompturi încărcate: {list(prompts.keys())}", flush=True)

results = []
corrected = 0
unchanged = 0
errors = 0

for i, r in enumerate(rows, 1):
    m = dict(r._mapping)
    email_id = m['id']
    cat_before = m['cat_before']
    cts_cat = m['cts_cat']

    # Fetch email complet
    email_row = db.execute(text(
        "SELECT id, subject, from_address, from_name, body_text, body_html, conversation_id, received_at "
        "FROM emails WHERE id=:id"
    ), {"id": email_id}).fetchone()
    if not email_row:
        errors += 1
        print(f"  [{i}/{total}] id={email_id} — NOT FOUND", flush=True)
        continue

    email = dict(email_row._mapping)

    # Reclasifică cu prompturile noi (force_fresh=True sare cache-ul)
    res = category_classifier.classify_category(email, prompts=prompts, force_fresh=True)
    if not res:
        errors += 1
        print(f"  [{i}/{total}] id={email_id} — EROARE clasificare", flush=True)
        continue

    cat_after = res.get('category')

    # Salvăm rezultatul nou în DB
    db.execute(text(
        "UPDATE emails SET ai_category=:c, ai_result=CAST(:r AS jsonb), "
        "ai_status='done', ai_processed_at=NOW() WHERE id=:id"
    ), {"c": cat_after, "r": _json.dumps(res), "id": email_id})
    db.commit()

    correct = (cat_after == cts_cat)
    if correct:
        corrected += 1
        status = "CORECTAT"
    else:
        unchanged += 1
        status = "INCA GRESIT"

    results.append({
        "id": email_id,
        "before": cat_before,
        "after": cat_after,
        "cts": cts_cat,
        "correct": correct,
        "subject": (m.get('subject') or '')[:60]
    })

    print(f"  [{i}/{total}] id={email_id} {cat_before}->{cat_after} (CTS={cts_cat}) — {status}", flush=True)
    time.sleep(0.05)  # mic delay sa nu spam-am AI

db.close()

print(f"\n=== REZULTAT FINAL ===", flush=True)
print(f"Total procesate: {total}", flush=True)
print(f"Corectate (acum = CTS): {corrected} ({corrected*100//total if total else 0}%)", flush=True)
print(f"Încă greșite: {unchanged}", flush=True)
print(f"Erori: {errors}", flush=True)

# Breakdown pe perechi before->after
from collections import Counter
pairs = Counter(f"{r['before']}->{r['after']} (CTS={r['cts']})" for r in results)
print("\nTop perechi:", flush=True)
for pair, n in pairs.most_common(15):
    print(f"  {n}x {pair}", flush=True)
