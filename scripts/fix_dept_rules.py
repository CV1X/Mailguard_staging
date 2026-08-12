#!/usr/bin/env python3
"""Fix reguli deterministe departamente:
1. itsbulgaria.com + отчет -> schimba contabilitate -> taxe_drum
2. 'cosmin' -> restrânge la 'cosmin.bogdan@cargotrack.ro' (evita false positives clienți)
"""
import sys, json
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
import json as _json

db = SessionLocal()

row = db.execute(text("SELECT value FROM settings WHERE key='department_rules'")).fetchone()
store = row[0] if row and row[0] else {"rules": []}
rules = store.get("rules", [])

changed = 0

for r in rules:
    # Fix 1: itsbulgaria -> taxe_drum
    if r.get("id") == "7be469d1" and r.get("department") == "contabilitate":
        old_dept = r["department"]
        r["department"] = "taxe_drum"
        r["note"] = "itsbulgaria raport zilnic toll -> taxe_drum"
        r["by"] = "iris-cc-fix-dept-rules-2026-07-20"
        print(f"Fix 1: id={r['id']} {old_dept} -> taxe_drum ({r.get('from')} + {r.get('subject')})")
        changed += 1

    # Fix 2: 'cosmin' -> 'cosmin.bogdan@cargotrack.ro'
    if r.get("id") == "54d9492e" and r.get("from") == "cosmin":
        r["from"] = "cosmin.bogdan@cargotrack.ro"
        r["note"] = "Cosmin Bogdan (@cargotrack.ro) pe email -> mobilitate"
        r["by"] = "iris-cc-fix-dept-rules-2026-07-20"
        print(f"Fix 2: id={r['id']} from='cosmin' -> 'cosmin.bogdan@cargotrack.ro'")
        changed += 1

store["rules"] = rules
db.execute(text(
    "INSERT INTO settings(key, value, description, updated_by, updated_at) "
    "VALUES('department_rules', CAST(:v AS jsonb), 'Reguli deterministe de incadrare pe departament', :by, NOW()) "
    "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_by=:by, updated_at=NOW()"
), {"v": _json.dumps(store), "by": "iris-cc-fix-dept-rules-2026-07-20"})
db.commit()
db.close()
print(f"\nTotal modificari: {changed}")
print("DONE")
