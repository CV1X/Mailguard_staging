#!/usr/bin/env python3
"""Backfill ai_summary pentru apeluri recente. Rulează direct pe server (fara auth)."""
import sys
import os
sys.path.insert(0, '/opt/iris-mailguard')
os.chdir('/opt/iris-mailguard')

from app.database import SessionLocal
from app.services.calls_summarizer import backfill_recent

days = int(sys.argv[1]) if len(sys.argv) > 1 else 4
print(f'Backfill ai_summary pentru ultimele {days} zile...')
db = SessionLocal()
try:
    result = backfill_recent(days, db)
    print(f'Done: {result}')
finally:
    db.close()
