"""Incadrare email pe DEPARTAMENT — consumer al canalului IRIS AI.

Rule-first: intai regulile deterministe (department_rules.match); doar daca nicio regula nu
loveste, intreaba AI-ul (cascada gemma -> Claude). Orice incertitudine / esec / departament
invalid -> FALLBACK 'suport_1'. NU exista stare 'necunoscut' la departament: fiecare email
ajunge obligatoriu pe un departament.

Reutilizeaza helperele de extragere a corpului ("citeste ultimul reply") din category_classifier
ca sa ramana sincron cu logica de categorie (semnatura/quote-strip).

Output (stocat in emails.ai_department_result jsonb; emails.ai_department = slug-ul):
  { "department": "<slug>", "confidence": 0..1|null, "reason": "<o propozitie RO>",
    "model": "rule|gemma|claude-*|curated|fallback", "rule_id"?: "...", ... }
"""
import os
import re
import hashlib
import logging
import unicodedata
from typing import Dict, Any, Optional

from sqlalchemy import text
from app.database import SessionLocal
from app.services import iris_ai
from app.services import department_rules
from app.services import phishing_detector as _pd
# Reutilizam (NU copiem) helperele de corp/atasamente din clasificatorul de categorie.
from app.services import category_classifier as C

logger = logging.getLogger("mailguard.department")

# slug -> eticheta afisata. Tine sincron cu department_rules.VALID_DEPARTMENTS.
DEPT_LABELS = {
    "suport_1": "Suport 1",
    "suport_2": "Suport 2",
    "suport_3": "Suport 3",
    "taxe_drum": "Taxe de drum",
    "contabilitate": "Contabilitate",
    "mobilitate": "Mobilitate",
    "recuperare_tva": "Recuperare TVA",
    "comercial": "Comercial",
}
DEPARTMENTS = list(DEPT_LABELS.keys())
EDITABLE = list(DEPT_LABELS.keys())   # toate cele 8 au prompt editabil
FALLBACK = "suport_1"

DEFAULT_PROMPTS: Dict[str, str] = {
    "suport_1": (
        "Departamentul GENERAL si implicit (catch-all). Aici intra cererile operationale concrete care "
        "nu apartin clar altui departament, precum si TOT ce este vag, neclar sau ambiguu.\n"
        "Tipuri:\n"
        "(1) ORDINE DE PLATA (OP-uri) / dovezi de plata cu seria de factura PPCB, PPBG, PPHU sau ASCF "
        "— acestea sunt procesate EXCLUSIV de Suport 1, indiferent de suma sau beneficiar.\n"
        "(2) ORDINE DE PLATA (OP-uri) / dovezi de plata in care NU se poate determina seria facturii "
        "din subiect sau corpul emailului (serie lipsa, text neclar, atasament fara mentiune serie) "
        "— fallback OBLIGATORIU pe Suport 1.\n"
        "(3) OP-uri sau dovezi de plata pentru taxe de drum sau pentru incarcari/alimentari de "
        "combustibil (cand nu exista context contabil explicit cu alta serie).\n"
        "(4) Cereri operationale generice (activari, modificari, intrebari de rutina) care nu se "
        "potrivesc cu un departament specific.\n"
        "(5) Cereri de ajutor/asistenta generice fara o tema clara de alt departament.\n"
        "(6) Mesaje scurte, neclare sau fara obiect precis.\n"
        "ATENTIE: cand ezitati intre doua departamente, sau cand mesajul e vag/scurt/fara semnal clar, "
        "-> alege suport_1. Este alegerea SIGURA cand nimic altceva nu se potriveste cu incredere."
    ),
    "suport_2": (
        "Calibrare rezervoare / senzori de combustibil si date tehnice de consum.\n"
        "Tipuri: (1) Emailuri prin care clientul TRIMITE un atasament legat de calibrarea rezervorului "
        "(tabel/fisier de calibrare, raport de calibrare). (2) Fisiere cu date tehnice de alimentari/"
        "consum trimise DE CLIENT pentru corelare cu telemetria proprie. (3) Cereri de (re)calibrare "
        "a senzorilor de combustibil.\n"
        "Indicii puternice: atasament cu nume care contine 'calibrare'/'calibration'/'rezervor'/'tank'/"
        "'alimentari'/'fuel' — TRIMIS DE CLIENT, nu notificare automata de la un furnizor.\n"
        "NU apartine acestui departament:\n"
        "- Notificari automate de tranzactie de la furnizori de card carburant (Smart Diesel, DKV, "
        "WEX, OMV, etc.) — acestea sunt dovezi financiare -> contabilitate.\n"
        "- Mesaje de tip 'Alimentare SD', 'Alimentare card', 'Tranzactie combustibil' venite de la "
        "furnizori externi -> contabilitate.\n"
        "- Un atasament GENERIC (PDF cu nume aleatoriu) sau o dovada de plata pe un mesaj gol -> "
        "suport_1."
    ),
    "suport_3": (
        "Suport dedicat pe firul lui Zoli Tyepak.\n"
        "Tipuri: (1) Emailuri trimise de Zoli Tyepak. (2) Raspunsuri (reply) pe un fir initiat de el sau "
        "adresate lui. (3) Solicitari in care el este interlocutorul principal.\n"
        "Indiciu: expeditorul sau firul contine 'zoli'/'tyepak'.\n"
        "ATENTIE: contextul persoanei primeaza — subiectul tehnic nu schimba departamentul daca "
        "interlocutorul ramane Zoli Tyepak."
    ),
    "taxe_drum": (
        "Taxe de drum / rovinieta / toll (sisteme electronice de taxare rutiera).\n"
        "Tipuri: (1) Cereri si notificari de rambursare a taxelor de drum (refund toll). (2) Notificari "
        "de utilizare neautorizata a drumului / taxa neplatita. (3) Mesaje de la sisteme/operatori de "
        "taxare (ex. HU-GO, DigiToll, idata) — de regula expeditori automati. (4) OP-uri/plati legate "
        "STRICT de taxe de drum, cand sunt clar identificate ca atare.\n"
        "Indicii: 'refund'/'rambursare', 'unauthorized road use', 'toll', 'rovinieta'.\n"
        "ATENTIE: chitantele/facturile de achizitie (ex. 'Purchase Receipt') si extrasele bancare "
        "apartin Contabilitatii, NU Taxe de drum."
    ),
    "contabilitate": (
        "Contabilitate / facturare / evidenta financiar-contabila.\n"
        "Tipuri:\n"
        "(1) Chitante si facturi (ex. 'Purchase Receipt from DigiToll', facturi furnizori).\n"
        "(2) Extrase de cont si tranzactii zilnice bancare (ex. 'Tranzactii zilnice').\n"
        "(3) Documente si corespondenta de la cabinete/firme de contabilitate (ex. URBAN & ASOCIATII).\n"
        "(4) Solicitari legate de inregistrari contabile, balante, situatii financiare.\n"
        "(5) ORDINE DE PLATA (OP-uri) / dovezi de plata cu o serie de factura IDENTIFICABILA in subiect "
        "sau corpul emailului, ALTA decat PPCB, PPBG, PPHU sau ASCF.\n"
        "CUM IDENTIFICI SERIA: orice prefix de litere majuscule atasat direct cifrelor din numarul "
        "documentului este SERIA (ex: 'ACTS939046' -> seria ACTS; 'PPDK00123' -> seria PPDK; "
        "'INV-2024-001' -> seria INV). Daca subiectul sau body-ul incepe/contine o combinatie de "
        "tip [LITERE][CIFRE], acele litere sunt seria. Daca seria nu e PPCB/PPBG/PPHU/ASCF -> "
        "contabilitate (AICI). Daca NU exista niciun prefix alfanumeric vizibil -> suport_1.\n"
        "ATENTIE: tine de evidenta financiara, NU de o disfunctionalitate tehnica. Subiectul trebuie "
        "sa fie contabil (factura, extras, chitanta, OP cu serie identificata non-PPCB/PPBG/PPHU/ASCF). "
        "NU orice mentiune de cost/plata genereaza contabilitate — un OP fara serie identificata "
        "merge la suport_1."
    ),
    "mobilitate": (
        "Mobilitate / detasare soferi si documente de transport international.\n"
        "Tipuri: (1) Declaratii si formulare pentru soferi: declaratii IMI (ex. subiect 'Declaratii "
        "Imi'), Macron (Franta), MiLoG (Germania), formular A1 — inclusiv schimburi unde clientul "
        "trimite permisul/actele soferului pentru intocmirea acestor declaratii. (2) Documente de "
        "detasare si conformitate pentru cursele internationale. (3) ORICE fir in care interlocutorul "
        "intern este Cosmin Bogdan (Reprezentare Europeana, cosmin.bogdan@cargotrack.ro) — chiar daca "
        "expeditorul curent e clientul care raspunde, iar semnatura/adresa lui Cosmin apare doar in "
        "istoricul citat al firului. (4) Corespondenta cu clienti din zona de mobilitate (ex. "
        "guretruck, transportinnood). (5) Notificari si documente de la CNPP (Casa Nationala de Pensii "
        "Publice) — adrese de tip @cnpp.ro, inclusiv noreply-a1@cnpp.ro sau orice subdomain cnpp.ro — "
        "acestea contin documente ale soferilor (drepturi de reprezentare, adeverinte, etc.).\n"
        "Indicii puternice: 'IMI', 'declaratii imi', 'Macron', 'MiLoG', 'A1', 'detasare', 'permis "
        "sofer', 'CNPP', 'cnpp.ro', 'Casa Nationala de Pensii', 'drepturi de reprezentare', "
        "prezenta lui 'Cosmin Bogdan' / 'cosmin.bogdan@cargotrack.ro' oriunde in fir, "
        "'guretruck', 'transportinnood'.\n"
        "ATENTIE: contextul de detasare/declaratii sofer primeaza — un reply scurt ('atasez permisul', "
        "'multumesc') pe un fir despre declaratii IMI ramane Mobilitate; foloseste subiectul firului "
        "ca semnal de rutare. Orice email cu expeditor @cnpp.ro -> mobilitate, fara exceptie."
    ),
    "recuperare_tva": (
        "Recuperare TVA si compensare.\n"
        "Tipuri: (1) Solicitari si documente de recuperare a TVA-ului din strainatate. (2) Imputerniciri/"
        "mandate pentru recuperare TVA. (3) Contracte NOI de compensare. (4) Intrebari si lamuriri pe "
        "zona de recuperare TVA / documente relevante.\n"
        "Indicii: 'recuperare TVA', 'TVA', 'compensare', 'imputernicire'.\n"
        "ATENTIE: chiar si o simpla intrebare despre recuperarea TVA-ului apartine acestui departament."
    ),
    "comercial": (
        "Comercial / vanzari / oferte.\n"
        "Tipuri: (1) Raspunsuri (reply) ale clientilor la emailurile noastre de promotie/campanie. "
        "(2) Cereri de oferte, oferte promotionale sau preturi. (3) Solicitari comerciale, interes "
        "pentru servicii noi sau upgrade.\n"
        "Indicii: 'oferta', 'promotie', 'pret', reply la o campanie trimisa de noi.\n"
        "ATENTIE: o cerere de oferta este Comercial chiar daca pare administrativa."
    ),
}

_BASE_HEAD = (
    "Esti un sistem care incadreaza emailuri de suport ale unei firme de monitorizare/telemetrie "
    "pentru transport in EXACT unul dintre departamentele de mai jos. Alege un SINGUR departament, "
    "cel mai potrivit dupa sensul mesajului.\n\n"
    "LIMBA: emailurile pot fi in orice limba; clasifica DUPA SENS, traducand mental daca e nevoie. "
    "NU scrie traducerea.\n\n"
    "DECIDE DOAR PE MESAJUL NOU (ultimul reply scris de expeditor), NU pe tot firul si NU pe subiectul "
    "mostenit. Subiectul (mai ales 'Fwd:'/'Re:' preluat) e doar context slab — NU ruta pe el singur.\n\n"
    "DISTRIBUTIA REALA (prior, foloseste-o): suport_1 ≈45%, contabilitate ≈24%, taxe_drum ≈11%, "
    "mobilitate ≈7%, suport_2 ≈5%, recuperare_tva ≈4%, comercial ≈3%. Deci suport_1 NU este alegerea "
    "implicita pentru ORICE — peste jumatate din emailuri apartin unui departament SPECIALIZAT. Cand "
    "MESAJUL NOU contine un semnal clar pentru un departament specializat (vezi indiciile de mai jos), "
    "ruteaza-l ACOLO cu incredere — NU te refugia in suport_1. Rezerva suport_1 pentru cereri cu adevarat "
    "generice/operationale, mesaje vagi/scurte fara semnal, sau cand chiar ezitezi intre doua departamente. "
    "NU exista 'necunoscut'.\n\n"
    "Vei vedea uneori o linie 'Atasamente: N' si 'Nume atasamente: ...'. PREZENTA unui atasament NU "
    "inseamna automat un anumit departament; conteaza NUMELE. Doar un atasament cu nume de calibrare/"
    "rezervor/combustibil (calibrare/calibration/rezervor/tank/alimentari/fuel) inclina spre suport_2. "
    "Un atasament GENERIC (PDF cu nume aleatoriu, o dovada de plata/OP/payment proof) pe un mesaj gol "
    "sau vag NU schimba departamentul -> suport_1.\n\n"
    "CAND muti de pe suport_1 (altfel raman suport_1):\n"
    "- mobilitate: mesajul nou e despre detasare / 'Declaratii IMI'/Macron/MiLoG/A1, sau trimite "
    "permisul/actele soferului pentru astfel de declaratii; SAU expeditorul e de la cnpp.ro "
    "(Casa Nationala de Pensii Publice) — documente soferi -> mobilitate fara exceptie.\n"
    "- recuperare_tva: mesajul nou cere/discuta recuperare TVA, compensare, imputernicire.\n"
    "- suport_2: CLIENTUL trimite date tehnice de calibrare rezervor / senzori combustibil "
    "(calibrare/rezervor/tank/fuel). IMPORTANT: notificarile automate de la furnizori de card "
    "carburant (Smart Diesel, DKV, WEX, OMV, 'Alimentare SD', 'tranzactie combustibil') NU sunt "
    "suport_2 — sunt dovezi financiare -> contabilitate. Un PDF generic sau OP -> suport_1.\n"
    "- comercial: mesajul nou e o cerere de oferta/pret sau raspuns la o campanie a noastra.\n"
    "- contabilitate: mesajul nou TRIMITE/discuta un document financiar real — factura, chitanta "
    "('Purchase Receipt'), extras de cont, tranzactii bancare. NU orice mentiune de cost/plata.\n"
    "- taxe_drum: mesajul nou e legat de servicii de taxe drum (toll). APARTINE taxe_drum: cereri de "
    "activare/reactivare servicii toll (E-toll, SENT-GEO, HU-GO, BGToll, Digitoll) pe vehicule; "
    "credentiale cont toll trimise de client; OP-uri/dovezi de plata pentru INCARCARE conturi toll "
    "(BGToll, HU-GO, Digitoll, E-toll, ITS Bulgaria, carGObox) — chiar daca emailul e scurt; "
    "rapoarte zilnice/saptamanale ITS Bulgaria (Дневен отчет / Daily summary for toll products); "
    "confirmari de activare/plata toll; probleme cu vehicul suspendat in sistem toll; "
    "forwarded notificari toll de la client care cere ajutor concret (nu doar trimis fara cerere).\n"
    "  EXCEPTIE ABSOLUTA taxe_drum: daca mesajul sau subiectul contine o serie de factura PPHU, PPCB, "
    "PPBG sau ASCF (orice format: PPHU44770, PPCB001, PPBG-123 etc.) — merge la suport_1, NU taxe_drum, "
    "chiar daca contextul e HU-GO sau toll. Aceste serii sunt facturi CargoTrack proprii pt Suport 1.\n"
    "- OP-uri / dovezi de plata: REGULA OBLIGATORIE — cauta in subiect si corpul emailului o serie de "
    "factura SAU contextul platii. DEFINITIE SERIE: orice prefix de 2-6 litere majuscule atasat direct "
    "cifrelor (ex. ACTS939046 -> seria ACTS; PPBG00123 -> seria PPBG; PPCB5678 -> PPCB).\n"
    "  * Seria PPCB, PPBG, PPHU sau ASCF -> suport_1 (intotdeauna, fara exceptie, inclusiv cand contextul e HU-GO/toll).\n"
    "  * ORICE alta serie identificata (ACTS, PPDK, PPPL, INV, FAC, etc.) -> contabilitate.\n"
    "  * OP/dovada plata pentru incarcare cont toll (BGToll, HU-GO, Digitoll, carGObox, ITS Bulgaria, "
    "E-toll) FARA serie PPHU/PPCB/PPBG/ASCF -> taxe_drum (chiar daca emailul e scurt).\n"
    "  * OP prezent fara serie si fara context toll -> suport_1.\n\n"
    "Departamentele (foloseste EXACT slug-ul din paranteza la 'department'):\n\n"
)


def _tail() -> str:
    slugs = " | ".join(DEPARTMENTS)
    return (
        "\n\nReturneaza DOAR un JSON valid, fara text in plus, fara ```, exact in forma:\n"
        '{"department":"' + slugs + '","confidence":<numar 0..1>,'
        '"reason":"<o singura propozitie scurta in romana>"}\n'
        "CONFIDENCE: fii onest — 0.90-1.0 incadrare clara; 0.70-0.85 plauzibil; sub 0.60 incert "
        "(in caz de incertitudine pune department='suport_1')."
    )


def load_prompts() -> Dict[str, str]:
    """Prompturile editabile pe departament (DB peste default-urile din cod)."""
    out = dict(DEFAULT_PROMPTS)
    try:
        db = SessionLocal()
        rows = db.execute(text("SELECT department, prompt_text FROM ai_department_prompts")).fetchall()
        db.close()
        for r in rows:
            dep = r._mapping["department"]
            txt = r._mapping["prompt_text"]
            if dep in EDITABLE and txt and txt.strip():
                out[dep] = txt
    except Exception as e:
        logger.warning("load_prompts (dept) DB failed, using defaults: %s", e)
    return out


def build_system_prompt(prompts: Optional[Dict[str, str]] = None) -> str:
    p = prompts or load_prompts()
    parts = []
    for slug in DEPARTMENTS:
        parts.append("=== " + DEPT_LABELS[slug] + " (" + slug + ") ===\n" + p[slug])
    return _BASE_HEAD + "\n\n".join(parts) + _tail()


def _attachment_names(email: Dict[str, Any], attachments=None) -> str:
    """Numele atasamentelor (pentru indiciul suport_2 = calibrare). Best-effort."""
    names = []
    try:
        if attachments is not None:
            for a in attachments:
                n = (a.get("name") if isinstance(a, dict) else None)
                if n:
                    names.append(str(n))
        elif email.get("id"):
            db = SessionLocal()
            rows = db.execute(text("SELECT name FROM attachments WHERE email_id=:id"),
                              {"id": email.get("id")}).fetchall()
            db.close()
            names = [r._mapping["name"] for r in rows if r._mapping["name"]]
    except Exception as e:
        logger.warning("attachment_names failed: %s", e)
    return ", ".join(names[:10])


def _content(email: Dict[str, Any], att_count: int, att_names: str) -> str:
    """Construieste continutul pentru rutarea pe DEPARTAMENT.

    DECIZIA SE IA PE ULTIMUL REPLY (mesajul nou scris efectiv de expeditor), NU pe tot firul si
    NU pe subiectul mostenit. Subiectul (mai ales un 'Fwd:'/'Re:' preluat) e doar context SLAB:
    un client care forwardeaza o notificare a unui tert (ex. 'toll violation') NU devine taxe_drum
    dupa cuvintele din subiect — ramane suport_1. Notificarile reale de la operatori (idata, HU-GO,
    DigiToll) si interlocutorii interni (Cosmin/Zoli) sunt prinse separat de regulile deterministe
    (pe expeditor/continut), care ruleaza INAINTEA AI-ului. Reutilizam _email_body (ultimul reply,
    quote-strip fiabil) ca mesaj nou.
    """
    subject = email.get("subject") or ""
    frm = ((email.get("from_name") or "") + " <" + (email.get("from_address") or "") + ">").strip()
    body = C._email_body(email)
    lines = ["Mesajul NOU al expeditorului (ACEASTA e baza deciziei — clasifica DUPA acest text):\n" + body,
             "De la: " + frm,
             "Subiect (poate fi mostenit dintr-un Fwd:/Re: — DOAR context slab; NU ruta pe el singur): " + subject]
    if att_count:
        lines.append("Atasamente: " + str(att_count))
    if att_names:
        lines.append("Nume atasamente: " + att_names)
    return "\n".join(lines).strip()


def _normalize(parsed: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(parsed, dict):
        return None
    dep = str(parsed.get("department") or "").strip().lower()
    if dep not in DEPARTMENTS:
        dep = FALLBACK   # niciodata 'necunoscut' — orice invalid cade pe suport_1
    try:
        conf = float(parsed.get("confidence"))
        conf = max(0.0, min(1.0, conf))
    except (TypeError, ValueError):
        conf = None
    reason = parsed.get("reason")
    reason = str(reason).strip()[:400] if reason else None
    return {"department": dep, "confidence": conf, "reason": reason}



def _strip_diac(s: str) -> str:
    """Normalizeaza diacriticele romanesti (a/a/i/s/t) pentru match tolerant.
    'Miclău' -> 'miclau', 'Mădălina' -> 'madalina'. Rezolva semnaturi cu diacritice
    fata de mapping fara diacritice (#53449/#53454 David Miclău vs 'Miclau Adrian-David')."""
    if not s:
        return ""
    # unicodedata NFKD desparte litera de accent; eliminam combining marks.
    nfkd = unicodedata.normalize("NFKD", s)
    out = "".join(c for c in nfkd if not unicodedata.combining(c))
    # ș/ț cu cedila (U+0219/U+021B) sunt deja tratate de NFKD; garantam s/t.
    return out.lower()


def _match_employee_signature(email: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Cauta un angajat CargoTrack in emailul curent (prioritar) sau in contextul citat.
    Returneaza rezultat de clasificare doar daca:
    - exista context @cargotrack.ro in body (email e legat de CargoTrack)
    - exista text citat (e un reply, nu un email nou)
    - un angajat din lista e gasit in mesajul nou SAU in body complet
    Prioritate: angajat gasit in mesajul nou (fara citate) > angajat gasit in citate.
    Previne false positives: un Kovacs Robert extern fara context CargoTrack nu va lovi.
    Match ANCORAT PE NUME DE FAMILIE (token[0] din mapping, format 'Nume Prenume[e]'):
    numele de familie e discriminant (rar), prenumele sunt frecvent duplicate intre
    angajati (ionut x3, robert x3...). Cerem surname prezent + >=1 prenume prezent.
    """
    body_text = _strip_diac(email.get("body_text") or "")
    body_html = (email.get("body_html") or "")

    # Verifica context CargoTrack: trebuie sa existe @cargotrack.ro in email
    if "@cargotrack.ro" not in body_text and "@cargotrack.ro" not in body_html.lower():
        return None

    # Detecteaza daca e reply (are text citat) — reduce false positives
    # was_stripped=False poate insemna si reply cu corp gol (clientul n-a scris nimic
    # inainte de citat) — nu excludem in acel caz, doar prioritizam new_content.
    try:
        new_content, _, was_stripped = _pd._new_content(email)
    except Exception:
        new_content, was_stripped = "", False

    # Verifica ca exista indiciu de reply: text citat detectat SAU pattern "a scris:" in body
    _REPLY_PAT = re.compile(r'(?:wrote:|a scris:|on .{0,100}wrote:|(?:în|la)\b.{0,100}a scris:)', re.I)
    has_reply_context = was_stripped or bool(_REPLY_PAT.search(body_text))
    if not has_reply_context:
        return None

    # Cauta angajati din lista
    db = SessionLocal()
    try:
        rows = db.execute(text(
            "SELECT name, department FROM employee_department_mapping WHERE enabled=TRUE ORDER BY name"
        )).fetchall()
    except Exception as e:
        logger.warning("employee_department_mapping query failed: %s", e)
        return None
    finally:
        db.close()

    new_text = _strip_diac(new_content or "")

    # Detecteaza surname-uri duplicate (dezambiguizare): daca 2 angajati au acelasi
    # nume de familie normalizat, cerem SI un prenume comun ca sa nu ii confundam.
    _surname_counts: Dict[str, int] = {}
    for row in rows:
        parts = _strip_diac(row._mapping["name"]).replace("-", " ").split()
        if parts:
            _surname_counts[parts[0]] = _surname_counts.get(parts[0], 0) + 1

    def _find_earliest(haystack: str):
        """Returneaza angajatul cu prima aparitie in text (cel mai devreme pozitionat).
        Match ANCORAT PE NUME DE FAMILIE: numele de familie (token[0] din mapping, format
        'Nume Prenume[e]') trebuie prezent, plus >=1 prenume. Numele de familie e
        discriminant; prenumele singure (David, Andrei, Robert...) sunt duplicate intre
        angajati => nu declanseaza singure. Tolereaza:
        - diacritice (haystack deja normalizat prin _strip_diac; partile la fel),
        - ordine libera (semnatura 'David Miclau' vs mapping 'Miclau ...'),
        - prenume mijlociu absent din semnatura ('Miclau Adrian-David' prinde pe 'David Miclau')."""
        best_pos, best_name, best_dept = len(haystack) + 1, None, None
        for row in rows:
            name_parts = _strip_diac(row._mapping["name"]).replace("-", " ").split()
            if len(name_parts) < 2:
                continue
            surname = name_parts[0]
            given = name_parts[1:]  # prenume (unul sau mai multe)
            s_pos = haystack.find(surname)
            if s_pos < 0:
                continue  # numele de familie ABSENT -> nu e semnatura acestui angajat
            given_pos = [haystack.find(g) for g in given]
            given_found = [p for p in given_pos if p >= 0]
            if not given_found:
                continue  # doar numele de familie, fara niciun prenume -> insuficient
            # Surname duplicat intre angajati -> cere macar 1 prenume (deja garantat mai sus);
            # earliest-position decide intre omonimi (comportament pastrat).
            first_pos = min([s_pos] + given_found)
            if first_pos < best_pos:
                best_pos = first_pos
                best_name = row._mapping["name"]
                best_dept = row._mapping["department"]
        return best_name, best_dept

    # Prioritate 1: angajat in mesajul nou (fara citate) — semnal puternic
    name, dept = _find_earliest(new_text) if new_text else (None, None)
    # Prioritate 2: fallback la body complet (angajat in citate) — prima aparitie
    if not name:
        name, dept = _find_earliest(body_text)

    if name:
        logger.info("Employee signature match: %s -> %s", name, dept)
        return {
            "department": dept,
            "confidence": 1.0,
            "reason": "Semnatura angajat identificata: " + name,
            "model": "employee_signature",
            "employee": name,
            "escalated": False,
        }
    return None


def _fallback(reason: str) -> Dict[str, Any]:
    return {"department": FALLBACK, "confidence": None, "reason": reason,
            "model": "fallback", "escalated": False}


def _classify_department_core(email: Dict[str, Any],
                        prompts: Optional[Dict[str, str]] = None,
                        attachments=None,
                        force_fresh: bool = False) -> Dict[str, Any]:
    """Returneaza intotdeauna un rezultat cu un departament valid (fallback suport_1).

    1) Reguli deterministe (expeditor/subiect) — daca lovesc, decid (confidence 1.0).
    2) Altfel AI (cascada gemma -> Claude), cu acelasi lever curated-bypass cu task sarat.
       `force_fresh=True` sare cascada/curated si cere direct un raspuns PROASPAT (no_cache).
    3) Orice esec / departament invalid / AI neconfigurat -> suport_1.
    """
    # 1) Reguli deterministe
    try:
        hit = department_rules.match(email)
    except Exception as e:
        logger.warning("department rules match failed: %s", e)
        hit = None
    if hit:
        dep, rule = hit
        return {"department": dep, "confidence": 1.0,
                "reason": "Regula determinista: " + (rule.get("note") or (
                    (("from~" + rule["from"]) if rule.get("from") else "") +
                    (((" + " if rule.get("from") else "") + "subiect~" + rule["subject"]) if rule.get("subject") else ""))),
                "model": "rule", "rule_id": rule.get("id"), "escalated": False}

    # 2) Employee signature matching (reply la un email CargoTrack cu angajat in semnatura)
    emp_match = _match_employee_signature(email)
    if emp_match:
        return emp_match

    # 3) AI
    if not iris_ai.is_configured():
        return _fallback("AI indisponibil — incadrat pe departamentul general.")

    att_n = C._attachment_count(email, attachments)
    att_names = _attachment_names(email, attachments)
    content = _content(email, att_n, att_names)
    if not content.strip() or len(content.strip()) < 3:
        return _fallback("Continut insuficient — incadrat pe departamentul general.")
    system = build_system_prompt(prompts)

    # Cale FRESH (reclasificare): ocoleste curated-cache ca prompturile CURENTE sa se aplice.
    # Task SARAT cu sha1(system+content) + no_cache=True (skip_cache la gateway), FARA learn.
    if force_fresh:
        _salt = hashlib.sha1((system + "\x1e" + content).encode("utf-8")).hexdigest()[:10]
        res = iris_ai.run_prompt(
            system, content, response_format="json",
            model_hint="claude-haiku-4-5-20251001",  # departament pe Haiku (idem cale normala)
            temperature=0.0, max_tokens=200,
            task="cargo360:email_department:" + _salt, email_id=email.get("id"), no_cache=True)
        if not res.get("ok"):
            return _fallback("Eroare AI (fresh) — incadrat pe departamentul general.")
        norm = _normalize(res.get("parsed"))
        if not norm:
            return _fallback("Raspuns AI invalid (fresh) — incadrat pe departamentul general.")
        norm["model"] = res.get("model")
        norm["fresh"] = True
        norm["escalated"] = True
        return norm

    # DEPARTAMENT: model FIX Haiku, FĂRĂ cache și FĂRĂ curated/learn (decizie 2026-07-23).
    # Cascada veche gemma->curated cu use_cache=True servea răspunsuri vechi memorate care
    # încadrau greșit (ex. mailuri Suport 1 rămâneau pe Contabilitate din cache curat).
    # Acum: fiecare mail e reevaluat PROASPĂT cu Haiku, task sărat cu sha1(system+content)
    # + no_cache=True => zero cache. Fără learn_scope => nu se mai populează curated-cache.
    _salt = hashlib.sha1((system + "\x1e" + content).encode("utf-8")).hexdigest()[:10]
    res = iris_ai.run_prompt(
        system, content, response_format="json",
        model_hint="claude-haiku-4-5-20251001",  # ID complet — „haiku" scurt cade pe sonnet la gateway
        temperature=0.0, max_tokens=200,
        task="cargo360:email_department:" + _salt,
        email_id=email.get("id"), no_cache=True,
    )
    if not res.get("ok"):
        logger.warning("department classify failed: %s", res.get("error"))
        return _fallback("Eroare AI — incadrat pe departamentul general.")
    norm = _normalize(res.get("parsed"))
    if not norm:
        return _fallback("Raspuns AI invalid — incadrat pe departamentul general.")
    norm["model"] = res.get("model")
    norm["escalated"] = False
    norm["from_cache"] = False
    return norm


def classify_department(email: Dict[str, Any],
                        prompts: Optional[Dict[str, str]] = None,
                        attachments=None,
                        force_fresh: bool = False) -> Dict[str, Any]:
    """Incadrare departament cu PODEA de incredere.

    Apeleaza logica de baza, apoi aplica regula: orice incadrare AI sub pragul de 90%
    (AI_CASCADE_THRESHOLD) este mutata pe departamentul sigur 'suport_1'. 90% este inca
    permis (>= prag ramane neschimbat). Regulile DETERMINISTE (expeditor/subiect — ex.
    Mobilitate pentru Cosmin, Taxe de drum de la adresele cunoscute) vin cu confidence=1.0,
    deci NU sunt afectate. Fallback-urile au confidence=None si sunt deja 'suport_1'.
    `force_fresh=True` ocoleste curated-cache (reclasificare cu prompturile curente)."""
    res = _classify_department_core(email, prompts=prompts, attachments=attachments,
                                    force_fresh=force_fresh)
    try:
        floor = float(os.getenv("AI_CASCADE_THRESHOLD", "0.90"))
    except (TypeError, ValueError):
        floor = 0.90
    conf = res.get("confidence")
    if res.get("department") != FALLBACK and conf is not None and conf < floor:
        orig = res.get("department")
        res = {
            "department": FALLBACK,
            "confidence": conf,
            "reason": ("Incredere %.0f%% sub pragul de %.0f%% pentru '%s' -> incadrat pe "
                       "departamentul sigur (Suport 1)." % (
                           conf * 100, floor * 100, DEPT_LABELS.get(orig, orig))),
            "model": res.get("model"),
            "escalated": res.get("escalated", False),
            "low_confidence_floor": True,
            "ai_department": orig,
            "ai_confidence": conf,
        }
    return res
