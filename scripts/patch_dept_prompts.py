#!/usr/bin/env python3
"""Patch chirurgical prompturi departamente: contabilitate, suport_2, taxe_drum."""
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

def get_prompt(dept):
    row = db.execute(text("SELECT prompt_text FROM ai_department_prompts WHERE department=:d"), {"d": dept}).fetchone()
    return row._mapping['prompt_text'] if row else ""

def save_prompt(dept, text_val):
    db.execute(text(
        "INSERT INTO ai_department_prompts (department, prompt_text, updated_at, updated_by) "
        "VALUES (:d, :p, NOW(), :by) "
        "ON CONFLICT (department) DO UPDATE SET prompt_text=:p, updated_at=NOW(), updated_by=:by"
    ), {"d": dept, "p": text_val, "by": "iris-cc-patch-dept-2026-07-20"})
    db.commit()
    print(f"  {dept}: salvat ({len(text_val)} chars)")

# ─── 1. CONTABILITATE ───────────────────────────────────────────────────────
# Problema: preia OP-uri/dovezi de plata pentru conturi taxe drum (BGToll, HU-GO etc.)
# si rapoarte zilnice bulgare toll (Дневен отчет ITS Bulgaria)
# Fix: excludere explicita in sectiunea NU apartin

p = get_prompt('contabilitate')
print(f"contabilitate inainte: {len(p)} chars")

# Inserăm înaintea "NU aparțin:" un bloc de excluderi clare
ANCHOR_CONTA = "NU aparțin: OP-uri cu seria PPCB/PPBG/PPHU/ASCF;"
INSERT_CONTA = (
    "EXCEPȚII CRITICE — NU aparțin contabilitate, merg la taxe_drum: "
    "ordine de plată (OP-uri) și dovezi/confirmări de plată pentru ÎNCĂRCAREA conturilor de taxe de drum "
    "(BGToll, HU-GO, Digitoll, E-toll, ITS Bulgaria, carGObox) — acestea aparțin taxe_drum, NU contabilitate, "
    "chiar dacă emailul conține 'OP', 'dovadă plată', 'confirmare electronică'; "
    "rapoarte zilnice/săptămânale de sume datorate pentru produse toll trimise de operatori externi "
    "(ex. Дневен отчет ITS Bulgaria / Daily summary for toll products) — aparțin taxe_drum; "
    "confirmări de plată pentru facturi proformă BGToll/HU-GO/Digitoll — aparțin taxe_drum. "
    "REGULA SIMPLĂ: dacă plata e pentru un cont de taxe drum (toll), merge la taxe_drum. "
    "Dacă plata e pentru servicii GPS/tahograf/mobilitate CargoTrack, merge la contabilitate. "
)
new_conta = p.replace(ANCHOR_CONTA, INSERT_CONTA + ANCHOR_CONTA)
if INSERT_CONTA in new_conta:
    save_prompt('contabilitate', new_conta)
else:
    print("  contabilitate: ANCHOR negasit, adaug la final")
    save_prompt('contabilitate', p + " " + INSERT_CONTA)

# ─── 2. SUPORT_2 ────────────────────────────────────────────────────────────
# Problema: ia emailuri despre activari/probleme E-toll, SENT-GEO, credentiale E-toll,
# descărcare carduri sofer in context taxe drum — toate merg la taxe_drum
# Fix: excludere explicita

p = get_prompt('suport_2')
print(f"suport_2 inainte: {len(p)} chars")

ANCHOR_S2 = "NU APARTINE:"
INSERT_S2 = (
    "EXCEPTII CRITICE — NU apartin suport_2, merg la taxe_drum: "
    "activare/reactivare servicii de taxe drum pe vehicule (E-toll Polonia, HU-GO Ungaria, "
    "SENT-GEO Polonia, BGToll Bulgaria, Digitoll Romania) — chiar daca emailul mentioneaza "
    "'activare', 'verificare', 'nu functioneaza pe Polonia/Ungaria'; "
    "credentiale (login/parola) pentru conturi E-toll, HU-GO, SENT-GEO trimise de client; "
    "descarcari de carduri sofer IN CONTEXT de taxe drum (carte verde, talon, acte vehicul "
    "pentru activare serviciu toll) — daca contextul e activare toll, merge la taxe_drum; "
    "confirmari de activare servicii toll ('sa activat pe Polonia', 'am verificat taxele de drum'); "
    "probleme cu transmisia/nerecunoasterea vehiculului IN SISTEM TOLL (nu in GPS) — taxe_drum. "
    "REGULA: daca emailul e despre un serviciu de taxe de drum (toll), merge la taxe_drum, "
    "NU la suport_2 (chiar daca contine 'verificare' sau 'nu functioneaza'). "
)
new_s2 = p.replace(ANCHOR_S2, INSERT_S2 + ANCHOR_S2, 1)
if INSERT_S2 in new_s2:
    save_prompt('suport_2', new_s2)
else:
    print("  suport_2: ANCHOR negasit, adaug la final")
    save_prompt('suport_2', p + " " + INSERT_S2)

# ─── 3. TAXE_DRUM — confirmare explicita ca preia aceste cazuri ─────────────
p = get_prompt('taxe_drum')
print(f"taxe_drum inainte: {len(p)} chars")

# Adaugam la sectiunea APARTINE un punct explicit pentru rapoartele ITS si OP-urile toll
ANCHOR_TD = "NU APARTIN:"
INSERT_TD = (
    "CAZURI EXPLICITE care aparțin taxe_drum (frecvente, important): "
    "(A) Rapoarte zilnice/săptămânale de sume datorate pentru produse toll trimise de operatori externi — "
    "ex. 'Дневен отчет ITS Bulgaria', 'Daily summary for toll products', rapoarte Toll4Europe; "
    "(B) Ordine de plată (OP-uri) și dovezi/confirmări de plată pentru ÎNCĂRCAREA conturilor toll: "
    "BGToll, HU-GO, Digitoll, E-toll, ITS Bulgaria, carGObox — chiar dacă emailul e scurt ('atașat OP'); "
    "(C) Activări/reactivări servicii toll pe vehicule (E-toll, SENT-GEO, HU-GO, BGToll) și "
    "corespondența asociată (credențiale cont, verificare activare, status activare); "
    "(D) Probleme cu serviciul toll (vehicul suspendat în sistem toll, amenzi pentru toll neachitat, "
    "vehicul nerecunoscut în sistem toll) — când clientul raportează problema CA URMARE a unui "
    "serviciu toll CargoTrack. "
)
new_td = p.replace(ANCHOR_TD, INSERT_TD + ANCHOR_TD, 1)
if INSERT_TD in new_td:
    save_prompt('taxe_drum', new_td)
else:
    print("  taxe_drum: ANCHOR negasit, adaug la final")
    save_prompt('taxe_drum', p + " " + INSERT_TD)

# ─── Verificare ─────────────────────────────────────────────────────────────
print("\nVerificare finala:")
for dept in ['contabilitate', 'suport_2', 'taxe_drum']:
    row = db.execute(text(
        "SELECT length(prompt_text) AS l, updated_at FROM ai_department_prompts WHERE department=:d"
    ), {"d": dept}).fetchone()
    print(f"  {dept}: {row._mapping['l']} chars, updated {row._mapping['updated_at']}")

db.close()
print("DONE")
