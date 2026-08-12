"""Generare SUGESTIE de reply auto (Faza 1) — consumer al canalului IRIS AI.

Scop: pentru fiecare email clean, IRIS propune un RASPUNS SCURT de preluare, in limbaj UMAN si uzual
(ca al colegilor din suport), al carui rol e sa TINA conversatia calda pana cand operatorul uman
revine cu detaliile. In Faza 1 e DOAR o sugestie afisata in modal — NU se trimite nimic.

IRIS isi da si un GRAD DE INCREDERE (0..1) ca un astfel de raspuns generic e potrivit pentru ACEST
email si nu induce clientul in eroare. Increderea mare (>=0.85) = preluare clara (confirmare, plata,
documente). Increderea mica = mailul cere ceva specific/sensibil unde un raspuns generic ar fi gresit
sau ar parea ca ignoram intrebarea — operatorul vede scorul si nu trimite ceva incert.

Output (stocat in emails.ai_autoreply + emails.ai_autoreply_result jsonb + emails.ai_autoreply_confidence):
  { "ok": bool, "text": "<raspunsul>", "confidence": 0..1|null, "model": "...", "reason"?: "..." }
"""
import logging
import re
from typing import Dict, Any, Optional

from sqlalchemy import text
from app.database import SessionLocal
from app.services import iris_ai

logger = logging.getLogger("mailguard.autoreply")

# Cheia in tabela KV `settings` pentru promptul editabil (mirror 'priority.classify_prompt').
PROMPT_KEY = "autoreply.generate_prompt"
# Faza 2: prompt separat pentru reply-ul de INCHIDERE (cand solicitarea a fost SOLUTIONATA in CTS).
PROMPT_SOLVED_KEY = "autoreply.generate_prompt_solved"

# Sub acest prag NU stocam nicio sugestie: un raspuns generic ar fi probabil gresit / nepotrivit
# si oricum nu s-ar trimite. Cerere user 2026-06-25.
MIN_CONFIDENCE = 0.60

# Domenii INTERNE (proprii): emailuri trimise de un coleg / sistem intern (inclusiv forward-uri
# Fw:/Fwd: intre colegi) NU primesc sugestie — nu raspundem unui mail intern. Cerere user 2026-06-25.
INTERNAL_DOMAINS = ("cargotrack.ro",)

# Sugeram reply DOAR la emailuri in romana. Daca modelul detecteaza alta limba (engleza, franceza,
# rusa, ucraineana, maghiara, moldoveneasca etc.) -> fara sugestie. Cerere user 2026-06-25.
ACCEPT_LANGS = {"ro", "ron", "rou", "romanian", "romana", "română", "roman"}

# Expeditori automati / interni / feed-uri pt care NU generam sugestie (raspunsul nu s-ar trimite).
SKIP_SENDERS = {
    "kudos@cargotrack.ro",
    "registru.release@cargotrack.ro",
}
# Pattern-uri de local-part care indica o adresa automata (no-reply, daemon, feed, registru, kudos).
_SKIP_LOCAL_RE = re.compile(
    r"^(no[-_.]?reply|do[-_.]?not[-_.]?reply|noreply|mailer-daemon|postmaster|bounce|"
    r"notifications?|notificari|alerts?|alerte|automat|robot|daemon|registru[._-]|kudos)\b",
    re.I)


_AUTOREPLY_AI_KEY = "processing.email_autoreply_ai_enabled"


def autoreply_ai_status() -> bool:
    """Starea switch-ului de generare AI sugestii reply (ambele task-uri). Absent/eroare => ON (fail-open)."""
    try:
        db = SessionLocal()
        row = db.execute(text("SELECT value FROM settings WHERE key=:k"),
                         {"k": _AUTOREPLY_AI_KEY}).fetchone()
        db.close()
        if not row or row[0] is None:
            return True
        v = row[0]
        return bool(v.get("enabled", True)) if isinstance(v, dict) else True
    except Exception:
        logger.warning("autoreply_ai_status failed — fail-open ON")
        return True


def set_autoreply_ai(enabled: bool, by: Optional[str] = None) -> bool:
    """START/STOP generarea AI a sugestiilor de reply pentru emailuri (runtime, fara restart)."""
    import json
    db = SessionLocal()
    try:
        db.execute(text("""
            INSERT INTO settings(key, value, updated_by, updated_at)
            VALUES (:k, CAST(:v AS jsonb), :by, now())
            ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_by=EXCLUDED.updated_by,
              updated_at=now()
        """), {"k": _AUTOREPLY_AI_KEY, "v": json.dumps({"enabled": bool(enabled)}), "by": by})
        db.commit()
    finally:
        db.close()
    return bool(enabled)


def _is_skip_sender(addr: str) -> bool:
    """True daca expeditorul e o adresa automata/interna careia nu i se raspunde."""
    a = (addr or "").strip().lower()
    if not a or "@" not in a:
        return False
    if a in SKIP_SENDERS:
        return True
    local = a.split("@", 1)[0]
    return bool(_SKIP_LOCAL_RE.match(local))


def _is_internal_sender(addr: str) -> bool:
    """True daca expeditorul e dintr-un domeniu intern (coleg/sistem). Mail intern => fara sugestie."""
    a = (addr or "").strip().lower()
    if "@" not in a:
        return False
    dom = a.split("@", 1)[1]
    return any(dom == d or dom.endswith("." + d) for d in INTERNAL_DOMAINS)

DEFAULT_PROMPT = (
    "Esti un coleg din echipa de suport CargoTrack (firma de monitorizare/transport). Scrii un "
    "RASPUNS SCURT pe care l-ai trimite clientului ca PRELUARE — sa stie ca i-am vazut mesajul si ca "
    "ne ocupam. Rolul mesajului e sa tina conversatia calda PANA cand un coleg revine cu detaliile / "
    "raspunsul concret. NU rezolvi tu problema in mesaj.\n\n"
    "LIMBAJ: uman, firesc, uzual, POLITICOS — exact cum vorbesc colegii din suport cu clientii. Scurt "
    "(de obicei 1 fraza, maxim 2), cald si amabil, fara limbaj corporatist rigid. Incepe de obicei cu "
    "'Buna ziua' si, unde se potriveste, incheie cu o multumire ('va multumim!'); fara semnatura.\n\n"
    "ADRESARE — GENERICA: NU folosi NICIODATA numele, prenumele sau functia clientului si NU inventa "
    "un nume, chiar daca apare in semnatura, in subiect sau in adresa de email. Foloseste doar formule "
    "generale: 'Buna ziua' / adresare cu 'dumneavoastra'. NICIODATA 'Buna ziua <nume>'.\n\n"
    "CONTEXT vs RASPUNS: poti primi ULTIMELE cateva mesaje din conversatie (ISTORIC), DOAR ca sa "
    "intelegi despre ce e vorba si sa alegi formularea generica potrivita. Raspunzi INSA EXCLUSIV la "
    "ULTIMUL mesaj al clientului. Istoricul NU se citeaza, NU se rezuma, NU se parafrazeaza inapoi.\n\n"
    "RASPUNS GENERIC — REGULA CENTRALA: raspunsul e o preluare GENERICA. NU include NICIUN identificator "
    "sau detaliu specific — nici numere de inmatriculare, VIN, numere de factura/contract/comanda/AWB, "
    "sume, date calendaristice, coduri, nume de persoane sau firme — CHIAR DACA apar in mesajul "
    "clientului sau in istoric. Acele detalii pot fi irelevante, eronate sau pot sa nu existe; daca le "
    "mentionezi, risti sa induci clientul in eroare. Confirmi DOAR ca am primit mesajul si ca revenim.\n\n"
    "EXEMPLE de ton si structura (asa sa sune); foloseste contextul ca sa alegi TIPUL, nu ca sa adaugi detalii:\n"
    "- client care confirma ceva simplu ('lasati-l activ, multumesc') -> 'In regula, va multumim!'\n"
    "- atasament / poza de tip ordin de plata sau dovada de plata -> 'Buna ziua, vom procesa plata in "
    "cel mai scurt timp posibil, va multumim!'\n"
    "- client care TRIMITE documente/atasamente (inclusiv cand mesajul nu are text, doar atasamente) -> "
    "'Buna ziua, am primit documentele, le vom procesa in cel mai scurt timp posibil, va multumim.'\n"
    "- client care CERE niste documente / un certificat -> 'Buna ziua, va vom pune la dispozitie "
    "documentele in cel mai scurt timp posibil.'\n"
    "- o sesizare/intrebare la care raspunde un coleg -> 'Am notat solicitarea, verificam si revenim "
    "in cel mai scurt timp.'\n"
    "- mesaj de INFORMARE / confirmare / instructiuni de la expeditor (te anunta ceva, confirma "
    "primirea, iti da niste instructiuni — NU iti cere sa rezolvi o problema) -> 'Buna ziua, am luat "
    "la cunostinta, va multumim!'\n"
    "- orice alta cerere care nu se incadreaza mai sus -> 'Buna ziua, am primit solicitarea "
    "dumneavoastra, o vom procesa in cel mai scurt timp posibil, va multumim!'\n\n"
    "REGULI DURE:\n"
    "- NU folosi numele clientului si nu te adresa pe nume (vezi ADRESARE).\n"
    "- NU inventa date, termene exacte, sume, numere de factura sau alte detalii concrete.\n"
    "- NU mentiona obiecte sau identificatori specifici (vehicul, numar de inmatriculare, cont, numar "
    "de factura/contract/AWB, suma, data) — raspunsul ramane GENERIC (vezi REGULA CENTRALA de mai sus).\n"
    "- NU insira, nu rezuma si nu parafraza inapoi instructiunile sau solicitarile punctuale ale "
    "clientului, si NU inventa niciun detaliu. GRESIT (insira instructiunile lui): 'am notat "
    "solicitarea privind trimiterea actelor in original si a copiei AWB-ului'. Ramai generic: 'am "
    "primit solicitarea dumneavoastra' / 'am luat la cunostinta'. Mesajul NU trebuie sa para ca "
    "recita inapoi lista clientului.\n"
    "- NU da raspunsul tehnic / nu rezolva intrebarea in mesaj — doar preiei si anunti ca revenim.\n"
    "- NU jigni, fara sarcasm, fara reprosuri catre client.\n"
    "- Scrie in romana, adresare cu 'dumneavoastra'. Raspunde DOAR cu textul mesajului (in campul "
    "JSON 'reply'), fara semnatura, fara ghilimele in jurul lui.\n\n"
    "GRAD DE INCREDERE ('confidence', 0..1): cat de sigur esti ca un astfel de raspuns generic de "
    "preluare e POTRIVIT pentru acest email si NU induce clientul in eroare.\n"
    "- Mare (>=0.85): preluare clara — confirmare simpla, dovada/ordin de plata, cerere de documente, "
    "multumire, mesaj de rutina.\n"
    "- Mijlocie (0.5-0.8): se potriveste, dar contextul e partial neclar.\n"
    "- Mica (<0.4): mailul cere un raspuns SPECIFIC pe care o preluare seaca l-ar trata gresit, ESTE "
    "o nemultumire/conflict unde un 'multumim' generic ar fi nepotrivit, sau contextul e prea neclar. "
    "La incredere mica, mai bine nu trimitem — operatorul decide."
)

# Faza 2 — reply de INCHIDERE (solicitarea a fost SOLUTIONATA de un coleg in CTS). Acelasi stil
# generic + constient de context ca preluarea, dar mesajul CONFIRMA ca cererea a fost procesata si
# rezolvata (de un coleg din echipa), nu ca abia o preluam.
DEFAULT_PROMPT_SOLVED = (
    "Esti un coleg din echipa de suport CargoTrack (firma de monitorizare/transport). Solicitarea "
    "clientului A FOST DEJA REZOLVATA de un coleg din echipa. Scrii un RASPUNS SCURT de INCHIDERE pe "
    "care i l-ai trimite clientului ca sa stie ca cererea lui a fost PROCESATA si SOLUTIONATA si ca "
    "ramanem la dispozitie daca mai are nevoie de ceva.\n\n"
    "LIMBAJ: uman, firesc, uzual, POLITICOS — exact cum vorbesc colegii din suport cu clientii. Scurt "
    "(de obicei 1 fraza, maxim 2), cald si amabil, fara limbaj corporatist rigid. Incepe de obicei cu "
    "'Buna ziua' si incheie cu o multumire ('va multumim!'); fara semnatura.\n\n"
    "ADRESARE — GENERICA: NU folosi NICIODATA numele, prenumele sau functia clientului si NU inventa "
    "un nume, chiar daca apare in semnatura, in subiect sau in adresa de email. Foloseste doar formule "
    "generale: 'Buna ziua' / adresare cu 'dumneavoastra'. NICIODATA 'Buna ziua <nume>'.\n\n"
    "CONTEXT vs RASPUNS: poti primi ULTIMELE cateva mesaje din conversatie (ISTORIC), DOAR ca sa "
    "intelegi despre ce solicitare e vorba si sa alegi formularea generica potrivita de inchidere. "
    "Istoricul NU se citeaza, NU se rezuma, NU se parafrazeaza inapoi.\n\n"
    "REGULA CENTRALA: mesajul confirma GENERIC ca solicitarea a fost procesata si solutionata de catre "
    "un coleg din echipa noastra (de un OM, nu automat). NU include NICIUN identificator sau detaliu "
    "specific — nici numere de inmatriculare, VIN, numere de factura/contract/comanda/AWB, sume, date "
    "calendaristice, coduri, nume de persoane sau firme — CHIAR DACA apar in mesajul clientului sau in "
    "istoric. NU descrie CUM s-a rezolvat si NU promite nimic in plus; doar confirmi ca s-a rezolvat si "
    "ca ramanem la dispozitie.\n"
    "NU RE-CONFIRMA PRIMIREA: la INCHIDERE nu repeta ce s-a spus deja la preluare — NU scrie 'am "
    "primit', 'am primit documentele/atasamentele', 'am primit solicitarea' sau 'am procesat "
    "documentele primite'. Clientul stie deja ca am primit mesajul; mergi DIRECT pe confirmarea ca "
    "solicitarea A FOST SOLUTIONATA (ex. 'solicitarea dumneavoastra a fost solutionata de un coleg din "
    "echipa noastra').\n\n"
    "EXEMPLE de ton si structura (asa sa sune); foloseste contextul ca sa alegi TIPUL, nu ca sa adaugi detalii:\n"
    "- plata / dovada de plata -> 'Buna ziua, plata a fost procesata, solicitarea dumneavoastra a fost "
    "solutionata. Va multumim!'\n"
    "- client care a CERUT documente / un certificat -> 'Buna ziua, v-am pus la dispozitie cele "
    "necesare; solicitarea dumneavoastra a fost solutionata. Va multumim!'\n"
    "- client care a TRIMIS documente de procesat -> 'Buna ziua, solicitarea dumneavoastra a fost "
    "procesata si solutionata de un coleg din echipa noastra. Va multumim!' (NU re-confirma primirea "
    "documentelor — asta s-a spus deja la preluare)\n"
    "- o sesizare / intrebare -> 'Buna ziua, solicitarea dumneavoastra a fost analizata si solutionata "
    "de un coleg. Va multumim!'\n"
    "- mesaj de informare / confirmare -> 'Buna ziua, am solutionat solicitarea dumneavoastra, va "
    "multumim!'\n"
    "- orice alt caz -> 'Buna ziua, solicitarea dumneavoastra a fost procesata si solutionata de un "
    "coleg din echipa noastra. Va multumim! Ramanem la dispozitie pentru orice alte detalii.'\n\n"
    "REGULI DURE:\n"
    "- NU folosi numele clientului si nu te adresa pe nume (vezi ADRESARE).\n"
    "- NU inventa date, termene, sume, numere de factura sau alte detalii concrete si NU descrie "
    "solutia tehnica.\n"
    "- NU mentiona obiecte sau identificatori specifici (vehicul, numar de inmatriculare, cont, numar "
    "de factura/contract/AWB, suma, data) — mesajul ramane GENERIC (vezi REGULA CENTRALA).\n"
    "- NU insira, nu rezuma si nu parafraza inapoi solicitarile punctuale ale clientului.\n"
    "- NU re-confirma primirea ('am primit', 'am primit documentele/atasamentele', 'am procesat "
    "documentele primite', 'am primit solicitarea') — la INCHIDERE mergi direct pe 'solicitarea "
    "dumneavoastra a fost solutionata'.\n"
    "- NU jigni, fara sarcasm, fara reprosuri catre client.\n"
    "- Scrie in romana, adresare cu 'dumneavoastra'. Raspunde DOAR cu textul mesajului (in campul "
    "JSON 'reply'), fara semnatura, fara ghilimele in jurul lui.\n\n"
    "GRAD DE INCREDERE ('confidence', 0..1): cat de sigur esti ca un mesaj GENERIC de inchidere e "
    "POTRIVIT pentru aceasta solicitare si NU induce clientul in eroare.\n"
    "- Mare (>=0.85): solicitare clara, de rutina, rezolvabila printr-o confirmare de inchidere "
    "(plata, documente, cerere simpla, informare).\n"
    "- Mijlocie (0.5-0.8): se potriveste, dar contextul e partial neclar.\n"
    "- Mica (<0.4): e o nemultumire/conflict sau o discutie sensibila unde un 'a fost solutionat' "
    "generic ar putea fi prematur/gresit, sau contextul e prea neclar. La incredere mica, mai bine nu "
    "trimitem — operatorul decide."
)


def _tail() -> str:
    return (
        "\n\nReturneaza DOAR un JSON valid, fara text in plus, fara ```, exact in forma:\n"
        '{"reply":"<mesajul scurt de preluare, in romana>","confidence":<numar 0..1>,'
        '"language":"<codul limbii MESAJULUI clientului: ro, en, fr, ru, uk, hu, de, it, ...>"}\n'
        "confidence = cat de potrivit e acest raspuns generic pentru email (vezi regulile).\n"
        "language = limba in care a scris CLIENTUL (nu a raspunsului tau). Raspunsul tau e mereu in "
        "romana; daca mesajul clientului NU e in romana, pune codul corect (ex 'en') si confidence mic."
    )


def load_prompt(kind: str = "new") -> str:
    """Promptul editabil (settings) peste default-ul din cod, in functie de tip:
    'new' -> preluare (autoreply.generate_prompt); 'solved' -> inchidere (autoreply.generate_prompt_solved)."""
    key = PROMPT_SOLVED_KEY if kind == "solved" else PROMPT_KEY
    default = DEFAULT_PROMPT_SOLVED if kind == "solved" else DEFAULT_PROMPT
    try:
        db = SessionLocal()
        row = db.execute(text("SELECT value FROM settings WHERE key=:k"), {"k": key}).fetchone()
        db.close()
        if row and row[0]:
            val = row[0]
            if isinstance(val, str) and val.strip():
                return val
    except Exception as e:
        logger.warning("load_prompt (autoreply, kind=%s) DB failed, using default: %s", kind, e)
    return default


def build_system_prompt(prompt: Optional[str] = None, kind: str = "new") -> str:
    p = prompt if (prompt and prompt.strip()) else load_prompt(kind)
    return p + _tail()


def _last_reply(email: Dict[str, Any]) -> str:
    """Doar ULTIMUL mesaj al clientului (fara istoricul citat), via quote-stripper-ul comun.

    NU cadem pe tot body-ul cand ultimul mesaj e gol: daca clientul a trimis doar un atasament
    (fara text nou), un fallback pe body ar reactiva istoricul vechi citat si IRIS ar raspunde la
    un mesaj depasit (vezi #35669). Gol = gol; cazul "doar atasamente" e tratat separat.
    """
    nt = nh = None
    try:
        from app.services import phishing_detector as _pd
        nt, nh, _ = _pd._new_content(email)
    except Exception:
        nt, nh = email.get("body_text"), email.get("body_html")
    joined = ((nt or "") + "\n" + (nh or "")).strip()
    return joined[:4000]


def _thread_context(email: Dict[str, Any], limit: int = 5) -> str:
    """Ultimele `limit` mesaje ANTERIOARE din aceeasi conversatie (fallback: acelasi expeditor),
    DOAR ca context — ca IRIS sa inteleaga situatia si sa aleaga formularea generica potrivita.
    Raspunsul se da insa EXCLUSIV la ultimul mesaj (vezi _content). Best-effort: la orice esec -> ''.

    Fiecare mesaj e redus la continutul NOU (fara istoric citat) si taiat la ~300 char: contextul
    ajuta la alegerea TIPULUI de raspuns, nu la preluarea de numere/identificatori (raspunsul ramane
    generic prin prompt)."""
    eid = email.get("id")
    if not eid:
        return ""
    conv = (email.get("conversation_id") or "").strip()
    frm = (email.get("from_address") or "").strip().lower()
    rows = []
    try:
        from app.services import phishing_detector as _pd
        db = SessionLocal()
        if conv:
            rows = db.execute(text(
                "SELECT body_text, body_html FROM emails "
                "WHERE conversation_id=:c AND id<>:id "
                "ORDER BY received_at DESC NULLS LAST LIMIT :n"),
                {"c": conv, "id": eid, "n": limit}).fetchall()
        elif frm:
            rows = db.execute(text(
                "SELECT body_text, body_html FROM emails "
                "WHERE lower(from_address)=:f AND id<>:id "
                "ORDER BY received_at DESC NULLS LAST LIMIT :n"),
                {"f": frm, "id": eid, "n": limit}).fetchall()
        db.close()
    except Exception as e:
        logger.warning("thread_context (autoreply) failed: %s", e)
        return ""
    parts = []
    # Cronologic (cel mai vechi -> cel mai nou), ca modelul sa urmareasca firul conversatiei.
    for r in reversed(rows):
        m = r._mapping
        try:
            nt, nh, _ = _pd._new_content({"body_text": m["body_text"], "body_html": m["body_html"]})
        except Exception:
            nt, nh = m["body_text"], m["body_html"]
        snippet = (nt or "").strip()
        if not snippet and nh:
            snippet = re.sub(r"<[^>]+>", " ", nh)
        snippet = re.sub(r"\s+", " ", snippet).strip()[:300]
        if snippet:
            parts.append("- " + snippet)
    return "\n".join(parts)


def _attachment_names(email: Dict[str, Any], attachments=None) -> str:
    """Numele atasamentelor — ca modelul sa recunoasca un OP / dovada de plata. Best-effort."""
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
        logger.warning("attachment_names (autoreply) failed: %s", e)
    return ", ".join(names[:10])


def _content(email: Dict[str, Any], att_names: str, last: str, thread: str = "", kind: str = "new") -> str:
    """Contextul pentru generare: subiect + expeditor + atasamente + ISTORIC (doar context) +
    ULTIMUL mesaj al clientului. kind='new' -> preluare; kind='solved' -> mesaj de inchidere
    (solicitarea a fost solutionata de un coleg)."""
    solved = (kind == "solved")
    subject = email.get("subject") or ""
    frm = ((email.get("from_name") or "") + " <" + (email.get("from_address") or "") + ">").strip()
    lines = [
        "Subiect email: " + subject,
        "De la client: " + frm,
    ]
    if att_names:
        lines.append("Atasamente: " + att_names +
                     " (daca par ordin/dovada de plata -> mesaj de plata; daca par documente/poze -> "
                     "mesaj de primire documente)")
    if thread:
        lines += [
            "",
            "ISTORIC RECENT al conversatiei (DOAR pentru context — NU raspunzi la aceste mesaje, "
            "NU le cita, NU prelua numere/identificatori din ele):",
            thread,
        ]
    if last:
        lines += [
            "",
            ("ULTIMUL mesaj al clientului din solicitarea SOLUTIONATA (foloseste-l doar ca sa alegi "
             "TIPUL de inchidere):" if solved else
             "ULTIMUL mesaj al clientului (LA ACESTA raspunzi):"),
            last,
        ]
    elif att_names and not solved:
        # Preluare fara text nou. Cu atasamente => clientul a trimis DOAR documente/poze (vezi #35669):
        # raspunzi DOAR la asta, NU la vreun mesaj mai vechi din istoric.
        lines += [
            "Ultimul mesaj al clientului NU contine text — a trimis DOAR atasamente "
            "(documente sau poze). NU raspunde la mesaje mai vechi din istoric; raspunde DOAR la "
            "faptul ca a trimis documente, cu mesajul de primire documente.",
        ]
    elif solved:
        # Inchidere fara text nou: confirmam generic solutionarea, fara a relua nimic din istoric.
        lines += [
            "Clientul nu a adaugat text nou de relevanta. Trimite mesajul GENERIC de inchidere/"
            "solutionare, fara a relua continut din istoric.",
        ]
    lines += [
        "",
        ("Genereaza mesajul scurt de INCHIDERE (confirmi GENERIC ca solicitarea a fost procesata si "
         "solutionata de un coleg) + gradul de incredere + limba, conform regulilor."
         if solved else
         "Genereaza raspunsul scurt de preluare GENERIC + gradul de incredere + limba, conform regulilor."),
    ]
    return "\n".join(lines).strip()


def _coerce_confidence(v) -> Optional[float]:
    try:
        f = float(v)
        return max(0.0, min(1.0, f))
    except (TypeError, ValueError):
        return None


def generate_autoreply(email: Dict[str, Any],
                       prompt: Optional[str] = None,
                       attachments=None,
                       kind: str = "new") -> Dict[str, Any]:
    """Genereaza sugestia de reply + gradul de incredere. Best-effort: la orice esec {ok:False}.
    kind='new' -> reply de PRELUARE (mail proaspat); kind='solved' -> reply de INCHIDERE
    (solicitarea a fost solutionata de un coleg in CTS)."""
    solved = (kind == "solved")
    if not iris_ai.is_configured():
        return {"ok": False, "text": "", "confidence": None, "model": None,
                "reason": "AI indisponibil — fara sugestie de reply."}

    if _is_skip_sender(email.get("from_address")):
        return {"ok": False, "text": "", "confidence": None, "model": None,
                "reason": "Expeditor automat/intern — fara sugestie de reply."}

    if _is_internal_sender(email.get("from_address")):
        return {"ok": False, "text": "", "confidence": None, "model": None,
                "reason": "Email intern (domeniu propriu) — fara sugestie de reply."}

    att_names = _attachment_names(email, attachments)
    last = _last_reply(email)
    if not solved and not last and not att_names:
        # PRELUARE fara text nou si fara atasamente -> nimic de preluat. NU raspundem la istoricul vechi.
        # (La INCHIDERE confirmam solutionarea chiar daca ultimul mesaj nu are text nou.)
        return {"ok": False, "text": "", "confidence": None, "model": None,
                "reason": "Mesaj fara continut nou si fara atasamente — nimic de preluat."}
    thread = _thread_context(email)
    content = _content(email, att_names, last, thread, kind=kind)
    system = build_system_prompt(prompt, kind=kind)

    # use_cache/learn=False: sugestia trebuie sa fie condusa de PROMPTUL curent, nu de raspunsuri
    # invatate anterior. Namespace separat pe tip (preluare vs inchidere) ca sa nu se amestece cache-ul.
    task = "cargo360:email_autoreply_solved_v2" if solved else "cargo360:email_autoreply_v7"
    res = iris_ai.run_prompt(
        system, content,
        response_format="json", temperature=0.3, max_tokens=300,
        task=task, email_id=email.get("id"),
        use_cache=False, learn=False,
    )
    if not res.get("ok"):
        logger.warning("autoreply generate failed: %s", res.get("error"))
        return {"ok": False, "text": "", "confidence": None, "model": res.get("model"),
                "reason": "Eroare AI — fara sugestie de reply."}
    parsed = res.get("parsed")
    if not isinstance(parsed, dict):
        return {"ok": False, "text": "", "confidence": None, "model": res.get("model"),
                "reason": "Raspuns AI invalid — fara sugestie de reply."}
    txt = (parsed.get("reply") or "").strip()
    if len(txt) >= 2 and txt[0] in "\"'`" and txt[-1] in "\"'`":
        txt = txt[1:-1].strip()
    if not txt:
        return {"ok": False, "text": "", "confidence": None, "model": res.get("model"),
                "reason": "Raspuns AI gol — fara sugestie de reply."}
    # Limba clientului: sugeram reply DOAR la emailuri in romana (cerere user 2026-06-25).
    lang = str(parsed.get("language") or "").strip().lower()
    if lang and lang not in ACCEPT_LANGS:
        return {"ok": False, "text": "", "confidence": _coerce_confidence(parsed.get("confidence")),
                "model": res.get("model"),
                "reason": "Email in limba straina (%s) — fara sugestie (raspundem doar in romana)." % lang}
    conf = _coerce_confidence(parsed.get("confidence"))
    if conf is not None and conf < MIN_CONFIDENCE:
        return {"ok": False, "text": "", "confidence": conf, "model": res.get("model"),
                "reason": ("Incredere %d%% sub pragul de %d%% — fara sugestie "
                           "(probabil nepotrivit de trimis)." %
                           (round(conf * 100), round(MIN_CONFIDENCE * 100)))}
    return {"ok": True, "text": txt[:2000], "confidence": conf, "model": res.get("model")}
