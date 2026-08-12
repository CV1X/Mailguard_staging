#!/usr/bin/env python3
"""Adaugă regula thread-uri la promptul sesizare și salvează în DB."""
import sys
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

db = SessionLocal()

# Citim promptul curent din DB
row = db.execute(text("SELECT prompt_text FROM ai_category_prompts WHERE category='sesizare'")).fetchone()
current = row._mapping['prompt_text'] if row else ""
print(f"Prompt curent: {len(current)} chars")

# Regula noua de adaugat la finalul sectiunii NU SUNT SESIZARI:
NEW_RULE = (
    "- Email care face parte dintr-un THREAD lung de conversație, iar MESAJUL CLIENTULUI "
    "din capăt este scurt și reprezintă o continuare/revenire administrativă la o discuție "
    "deja în curs (ex. 'Da, corect', 'Mulțumesc', 'Bine, așteptăm', 'Nici ieri nu a transmis "
    "când era în Serbia' ca răspuns la o explicație CargoTrack că dispozitivul e configurat "
    "să nu transmită în afara UE) → INFORMAȚIE dacă CargoTrack a oferit deja o explicație "
    "și clientul confirmă/continuă dialogul fără a raporta o problemă NOU apărută.\n"
    "- Email în care clientul raportează că 'nu funcționează' dar CONTEXTUL threadului arată "
    "că e parte dintr-un proces de activare în curs (pași de urmat, documente de trimis) "
    "→ INFORMAȚIE (problemă de activare în curs, nu dispozitiv defect)."
)

# Inserăm înaintea liniei "Ton agresiv/iritare SINGUR"
ANCHOR = "- Ton agresiv/iritare SINGUR nu face sesizare"
if ANCHOR in current:
    new_prompt = current.replace(ANCHOR, NEW_RULE + "- Ton agresiv/iritare SINGUR nu face sesizare")
    print("Regula inserată cu succes")
else:
    # fallback: adaugam la finalul sectiunii NU SUNT SESIZARI
    new_prompt = current + "\n" + NEW_RULE
    print("ANCHOR negăsit — adăugat la final")

db.execute(text(
    "UPDATE ai_category_prompts SET prompt_text=:p, updated_at=NOW(), updated_by=:by "
    "WHERE category='sesizare'"
), {"p": new_prompt, "by": "iris-cc-patch-thread-2026-07-20"})
db.commit()
print(f"Salvat: {len(new_prompt)} chars")

# Verificare
row2 = db.execute(text("SELECT length(prompt_text) AS l, updated_at FROM ai_category_prompts WHERE category='sesizare'")).fetchone()
print(f"DB: {row2._mapping['l']} chars, updated {row2._mapping['updated_at']}")
db.close()
print("DONE")
