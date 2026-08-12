#!/usr/bin/env python3
"""Salvează prompturile regenerate din CTS (rulat direct pe server după generare)."""
import sys
sys.path.insert(0, '/opt/iris-mailguard')

# Încarcă .env
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

NEW_PROMPTS = {
    "informatie": (
        "Se încadrează la INFORMAȚIE orice email care NU raportează o problemă activă a unui "
        "dispozitiv/serviciu propriu al clientului și NU exprimă nemulțumire față de un eșec "
        "anterior al companiei.\n\n"
        "APARȚIN INFORMAȚIEI:\n"
        "1. Cereri de informații, lămuriri, clarificări (inclusiv vagi) fără raportarea unei disfuncționalități.\n"
        "2. Solicitări administrative/operaționale: implementare user/șofer, activare serviciu, mutare vehicul, "
        "procesare documente, trimitere acte/contracte, furnizare informații, răspunsuri la solicitări de documente.\n"
        "3. Confirmări: confirmare plată efectuată (inclusiv prin canal alternativ: cash la echipa de montaj), "
        "programare, discuție anterioară, trimitere documente, confirmare primire tichet.\n"
        "4. Actualizări de status operațional: locație vehicul, intrare/ieșire țară, finalizare cursă/descărcare.\n"
        "5. Redirectionare/transfer: stabilire limbă, transfer la coleg, revenire ulterioară.\n"
        "6. Apeluri fără obiect: greșeală, pierdut, verificare generală, non-clienți care întreabă ce face compania.\n"
        "7. Clarificări tehnice fără disfuncționalitate (tonaj, masă, funcționalități platformă, încărcare documente/poze).\n"
        "8. Clarificări financiare/facturare fără contestare (confirmare plată, suspendare temporară, "
        "stabilire facturare, info taxe drum).\n"
        "9. Comunicări procedurale: modificări procedură, instrucțiuni, suspendări temporare.\n"
        "10. Confirmări de rezolvare: problemă anterioară s-a rezolvat, fără sesizare nouă. Inclusiv "
        "notificări automate de tip 'tichet rezolvat', 'problemă remediată'.\n"
        "11. Indisponibilitate și reprogramare: nu poate continua, cere amânare, fără a semnala o problemă.\n"
        "12. Notificări automate de sistem fără legătură cu o problemă activă a clientului (confirmare creare "
        "tichet, confirmare înregistrare vehicul, confirmare ștergere vehicul, confirmare asociere OBU/cont, "
        "răspunsuri automate de primire).\n"
        "13. Emailuri fără conținut substantiv: fără subiect și fără mesaj real, conținând doar semnătură "
        "automată, salut scurt sau corp gol.\n"
        "14. Răspunsuri ale CargoTrack către client (nu ale clientului) sau notificări interne de sistem "
        "fără problemă nouă.\n"
        "15. Transmitere de documente, confirmări de acțiuni sau răspunsuri la solicitări administrative, "
        "fără a semnala o problemă.\n"
        "16. Discuții despre litigii/dosare în instanță sau sume contestate juridic.\n"
        "17. Cereri de STATUS despre comenzi/activări/livrări ('când vine dispozitivul?', 'când se activează?', "
        "'totul este bine?') — acestea sunt cereri de informații, NU sesizări.\n"
        "18. Notificări externe (HU-GO, Digitoll, Bulgaria etc.) privind încălcări, penalizări sau utilizare "
        "neautorizată la care clientul REACȚIONEAZĂ sau cere lămuriri — acestea sunt notificări administrative "
        "externe, NU probleme ale dispozitivului/serviciului propriu.\n"
        "19. Emailuri în care clientul confirmă că a făcut o acțiune ('am alimentat', 'am plătit', 'am trimis "
        "documentele') — chiar dacă tonul e iritat, dacă nu raportează o problemă tehnică activă, este INFORMAȚIE.\n"
        "20. Emailuri în care clientul cere verificare/confirmare ('verificați dacă au intrat banii', 'verificați "
        "dacă totul este bine', 'actualizați disponibilul') fără a raporta o eroare concretă — acestea sunt "
        "cereri de confirmare, NU sesizări.\n\n"
        "NU APARȚIN INFORMAȚIEI:\n"
        "- Emailuri în care clientul raportează că un dispozitiv/serviciu propriu NU funcționează: lipsa semnal, "
        "card inactiv, sold care nu scade, semnal întrerupt, aplicație care nu merge, dispozitiv care nu "
        "transmite, rută care nu apare.\n"
        "- Emailuri în care clientul raportează că NU poate efectua o acțiune din cauza unei erori: plată "
        "eșuată, opțiune lipsă în aplicație, link invalid, cont suspendat, aplicație care nu funcționează.\n"
        "- Emailuri în care clientul întreabă DE CE apare o situație anormală care indică o eroare: suma în "
        "minus, două facturi pentru aceeași perioadă, plată pe vehicul greșit, factura fără TVA, sold prea "
        "mare, sold care nu scade.\n"
        "- Emailuri în care clientul raportează că o problemă persistă sau că nu s-a rezolvat.\n"
        "- Emailuri în care clientul contestă o factură, o sumă, o taxă sau solicită corectarea unei erori "
        "de facturare.\n"
        "- Notificări automate de tichet intern care descriu o problemă tehnică activă în curs de rezolvare.\n"
        "- Emailuri care conțin informații despre tranzacții retrase/penalizări aplicate și cer verificare "
        "sau contestare.\n"
        "- Rapoarte zilnice de tranzacții de la procesatori de plăți (ex. EuPlătesc).\n"
        "- Notificări automate de la sisteme externe (HU-GO, Digitoll etc.) privind înregistrare/ștergere "
        "vehicul, asociere/disociere OBU, atribuire vehicul la cont — FĂRĂ reacție a clientului (acestea "
        "sunt notificări pure de sistem)."
    ),

    "sesizare": (
        "Se încadrează la SESIZARE orice email în care clientul raportează PENTRU PRIMA DATĂ o problemă "
        "activă, disfuncționalitate, eroare sau neconcordanță (tehnică, funcțională, administrativă sau "
        "financiară) a unui dispozitiv/serviciu propriu și așteaptă intervenție/remediere din partea CargoTrack.\n\n"
        "TIPURI DE SESIZĂRI:\n"
        "1. Probleme financiare/administrative: debitări incorecte, facturi greșite, plăți duble, sume "
        "necunoscute, discrepanțe între sume, plată atribuită greșit unui vehicul, două facturi pentru "
        "aceeași perioadă, facturi fără TVA.\n"
        "2. Erori de aplicație/software: nu merge descărcarea, dă eroare, nu se actualizează, versiune "
        "veche, nu se poate genera token, nu se poate sincroniza, card inactiv în aplicație.\n"
        "3. Probleme cu dispozitive/carduri: card inactiv/nu funcționează, tahograf nu citește, dispozitiv "
        "defect, erori tahograf, semnal lipsă/întrerupt, semnal slab.\n"
        "4. Probleme de transmisie/vizualizare date: nu transmite, nu se vede mașina, locație greșită, date "
        "care nu coincid, transmisie intermitentă, lipsa semnal, sold care nu scade.\n"
        "5. Probleme de acces/conectivitate: nu pot accesa platforma, nu mă pot loga, cont blocat.\n\n"
        "NU SUNT SESIZĂRI:\n"
        "- Notificări externe (amenda HU-GO, Digitoll, Bulgaria, toll violation, unauthorized road use) la "
        "care clientul cere lămuriri, confirmă primirea sau reacționează fără a raporta o problemă proprie "
        "a dispozitivului/serviciului → INFORMAȚIE.\n"
        "- Notificări automate de la sisteme externe (HU-GO, Digitoll) privind înregistrare/ștergere vehicul, "
        "asociere/disociere OBU, atribuire vehicul la cont → INFORMAȚIE.\n"
        "- Rapoarte zilnice de tranzacții de la procesatori de plăți (EuPlătesc) → INFORMAȚIE.\n"
        "- Cereri de status despre comandă/activare/livrare ('când vine dispozitivul?', 'când se activează?', "
        "'este bine așa?') → INFORMAȚIE.\n"
        "- Confirmări de acțiuni efectuate ('am alimentat', 'am plătit', 'am trimis documentele') → INFORMAȚIE "
        "chiar dacă tonul e iritat.\n"
        "- Cereri administrative pure (trimite document, activează serviciu, furnizează informație, verifică "
        "dacă plata a intrat, actualizează disponibil) fără nicio problemă raportată → INFORMAȚIE.\n"
        "- Link invalid/expirat pentru portal documente → INFORMAȚIE (cerere de retrimitere link, nu problemă "
        "tehnică a dispozitivului).\n"
        "- Cont suspendat automat pentru sold negativ → INFORMAȚIE (notificare automată sistem, nu problemă "
        "tehnică raportată de client).\n"
        "- Ton agresiv/iritare SINGUR nu face sesizare: trebuie raportată o problemă tehnică/funcțională "
        "concretă a dispozitivului/serviciului.\n\n"
        "REGULI CLARE:\n"
        "- Dacă clientul raportează că dispozitivul NU funcționează, nu transmite, nu vede ruta, card nu "
        "merge, aplicația dă eroare → SESIZARE.\n"
        "- Dacă clientul cere STATUS/confirmare/lămuriri despre o notificare externă sau o acțiune "
        "administrativă → INFORMAȚIE.\n"
        "- Dacă clientul exprimă nemulțumire că o problemă ANTERIOARĂ nu a fost rezolvată, cu referire "
        "la contactări anterioare eșuate → verifică RECLAMAȚIE."
    ),

    "reclamatie": (
        "Se încadrează la RECLAMAȚIE emailul în care clientul exprimă nemulțumire EXPLICITĂ față de modul "
        "în care compania a gestionat (sau nu) o problemă ANTERIOARĂ. Necesită DOUĂ elemente obligatorii: "
        "(1) existența unei probleme/contactări anterioare și (2) eșecul companiei de a răspunde/rezolva.\n\n"
        "Indicatori OBLIGATORII:\n"
        "- Referință explicită la contactări anterioare fără răspuns ('v-am scris și nu a răspuns nimeni', "
        "'am sunat de două ori', 'nu m-a contactat nimeni').\n"
        "- Reminder/follow-up cu nemulțumire ('revin pentru a treia oară', 'încă aștept rezolvare').\n"
        "- Promisiuni nerespectate ('mi s-a spus că se rezolvă și nu s-a întâmplat').\n"
        "- Amenințări de reziliere CA URMARE a unui eșec anterior documentat ('dacă nu se remediază "
        "problemele dorim să renunțăm' DUPĂ ce s-a menționat că problema persistă din contactări anterioare).\n\n"
        "NU ESTE RECLAMAȚIE:\n"
        "- Raportarea PRIMEI APARIȚII a unei probleme tehnice, chiar cu ton agresiv sau cerere de reducere "
        "→ SESIZARE.\n"
        "- Nemulțumire față de o NOTIFICARE EXTERNĂ (suspendare automată, amendă primită) fără referință "
        "la eșec anterior al companiei → SESIZARE dacă raportează problema prima dată, INFORMAȚIE dacă "
        "doar confirmă/clarifică.\n"
        "- Solicitare de programare/status fără răspuns, FĂRĂ a menționa explicit că este a doua/a treia "
        "încercare → INFORMAȚIE (chiar dacă spune 'nu am fost contactat', dacă e prima mențiune a acestui fapt).\n"
        "- Amenințare de reziliere la PRIMA raportare a unei probleme → SESIZARE.\n"
        "- 'Nu mi-ați dat niciun răspuns' fără context anterior în email → INFORMAȚIE (poate fi o percepție, "
        "nu o reclamație documentată).\n"
        "- Amenzi repetate FĂRĂ mențiunea că problema a fost raportată anterior și ignorată → SESIZARE "
        "(raportare nouă de problemă recurentă).\n\n"
        "DIFERENȚA CRITICĂ:\n"
        "- SESIZARE = problema raportată ACUM, chiar dacă e recurentă sau gravă.\n"
        "- RECLAMAȚIE = problema raportată ANTERIOR + compania nu a rezolvat/răspuns + clientul REVINE "
        "cu nemulțumire explicită."
    ),
}

db = SessionLocal()
for cat, new_prompt in NEW_PROMPTS.items():
    db.execute(text(
        "INSERT INTO ai_category_prompts (category, prompt_text, updated_at, updated_by) "
        "VALUES (:c, :p, NOW(), :by) "
        "ON CONFLICT (category) DO UPDATE SET prompt_text=:p, updated_at=NOW(), updated_by=:by"
    ), {"c": cat, "p": new_prompt, "by": "iris-cc-regen-cts-2026-07-20"})
    db.commit()
    print(f"{cat}: saved ({len(new_prompt)} chars)", flush=True)

rows = db.execute(text("SELECT category, length(prompt_text) AS l, updated_at FROM ai_category_prompts ORDER BY category")).fetchall()
for r in rows:
    print(f"  DB {r._mapping['category']}: {r._mapping['l']} chars, updated {r._mapping['updated_at']}", flush=True)
db.close()
print("DONE", flush=True)
