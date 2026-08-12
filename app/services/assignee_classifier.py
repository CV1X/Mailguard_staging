"""Asignare email pe UTILIZATOR CargoTrack (OPS-2026-0131) — consumer al canalului IRIS AI.

Identifica persoana CargoTrack responsabila de un email de suport, STRICT pe baza unei surse
sigure din firul de discutie:
  1) email-match: o adresa @cargotrack.ro a unui angajat din lista (Setari -> Utilizatori) apare
     in corpul complet (inclusiv istoricul citat) — cel mai tare semnal (cheia de join CTS).
  2) name-match (fuzzy, order-independent): numele unui angajat (nume + prenume, tolerant la
     inversare / middle name) apare ca semnatura in fir.
Daca exista mai multi candidati -> AI dezambiguizeaza alegand EXACT un assignee dintre ei (sau
null); AI NU inventeaza adrese. Daca nu exista niciun candidat cert -> NEASIGNAT.

Reguli de precizie (confirmate cu userul):
  * mail nou / fara reply (fara context citat @cargotrack.ro) -> NEASIGNAT;
  * persoana identificata e in CONCEDIU la data emailului (employee_schedule local) -> NEASIGNAT +
    needs_review (sugestia se pastreaza in rezultat pentru transparenta).

Disponibilitatea se verifica LOCAL (employee_schedule, sincronizat zilnic), NU prin endpoint extern.

Output (stocat in emails.ai_assignee_result jsonb; emails.ai_assignee = email @cargotrack.ro | NULL):
  { "assignee_email": "x@cargotrack.ro|null", "assignee_name": str|null, "assignee_id": int|null,
    "department": "<slug>|null", "confidence": 0..1|null, "reason": "<o propozitie RO>",
    "model": "email|signature|ai|none|fallback", "candidates": [...],
    "needs_review"?: bool, "on_leave"?: bool, "suggested_email"?: str }
"""
import os
import re
import logging
from typing import Dict, Any, Optional, List

from sqlalchemy import text
from app.database import SessionLocal
from app.services import iris_ai
# Reutilizam (NU copiem) helperele de corp/atasamente + detectia de reply.
from app.services import category_classifier as C
from app.services import phishing_detector as _pd

logger = logging.getLogger("mailguard.assignee")

# Domeniul intern: doar adresele de aici pot fi assignee.
CARGOTRACK_DOMAIN = "@cargotrack.ro"

# Cheia in tabela KV `settings` pentru promptul editabil de dezambiguizare.
PROMPT_KEY = "assignee.classify_prompt"

_EMAIL_RE = re.compile(r"[a-z0-9][a-z0-9._%+\-]*@cargotrack\.ro", re.IGNORECASE)
_WORD_SPLIT = re.compile(r"[^a-z0-9]+")

# Cuvinte din nume prea generice ca sa conteze singure la name-match.
_STOPNAME = {"de", "la", "el", "ana", "ion"}

DEFAULT_PROMPT = (
    "Esti un sistem care identifica PERSOANA CargoTrack responsabila de tratarea unui email de "
    "suport, pe baza firului de discutie. Primesti: mesajul (cu istoricul citat), departamentul "
    "in care a fost incadrat si o LISTA DE CANDIDATI (angajati CargoTrack gasiti deja in fir prin "
    "adresa @cargotrack.ro sau semnatura). Alegi EXACT un singur assignee_email DIN LISTA de "
    "candidati DOAR daca firul indica clar ca acea persoana se ocupa de caz (a raspuns clientului, "
    "semneaza raspunsul, sau este indicata explicit ca responsabil). Daca nu poti decide cu "
    "siguranta intre candidati, sau niciunul nu pare responsabilul real, intorci assignee_email=null. "
    "NU inventa adrese in afara listei. Departamentul e doar un indiciu de coerenta (un candidat din "
    "departamentul incadrat e mai probabil responsabilul), NU un motiv suficient singur."
)


def _tail(candidates: List[Dict[str, Any]]) -> str:
    opts = " | ".join('"' + c["email"] + '"' for c in candidates) + ' | null'
    return (
        "\n\nReturneaza DOAR un JSON valid, fara text in plus, fara ```, exact in forma:\n"
        '{"assignee_email":' + opts + ',"confidence":<numar 0..1>,'
        '"reason":"<o singura propozitie scurta in romana>"}\n'
        "assignee_email TREBUIE sa fie una dintre adresele candidatilor de mai sus, sau null. "
        "Daca nu esti sigur -> null (preferam neasignat fata de o asignare gresita)."
    )


def load_prompt() -> str:
    try:
        db = SessionLocal()
        row = db.execute(text("SELECT value FROM settings WHERE key=:k"), {"k": PROMPT_KEY}).fetchone()
        db.close()
        if row and row[0]:
            val = row[0]
            if isinstance(val, str) and val.strip():
                return val
    except Exception as e:
        logger.warning("load_prompt (assignee) DB failed, using default: %s", e)
    return DEFAULT_PROMPT


def build_system_prompt(candidates: List[Dict[str, Any]], prompt: Optional[str] = None) -> str:
    p = prompt if (prompt and prompt.strip()) else load_prompt()
    lines = [p, "\n\nCANDIDATI (angajati CargoTrack gasiti in fir):"]
    for c in candidates:
        lines.append("- " + c["email"] + " (" + (c.get("name") or "?") + ", departament: "
                     + (c.get("department") or "?") + ")")
    return "".join([lines[0], lines[1], "\n" + "\n".join(lines[2:])]) + _tail(candidates)


# ── lista angajati (Setari -> Utilizatori) ───────────────────────────────────
def _load_employees() -> List[Dict[str, Any]]:
    """Angajatii activi cu email — sursa de adevar pentru matching. Best-effort."""
    try:
        db = SessionLocal()
        rows = db.execute(text(
            "SELECT id, name, email, department FROM employee_department_mapping "
            "WHERE enabled=TRUE AND email IS NOT NULL AND email <> '' ORDER BY name")).fetchall()
        db.close()
        return [dict(r._mapping) for r in rows]
    except Exception as e:
        logger.warning("_load_employees failed: %s", e)
        return []


def _name_tokens(emp: Dict[str, Any]) -> set:
    """Tokeni semnificativi ai persoanei, din NUME si din local-part-ul emailului
    (ex. 'madalina.apetrei' -> {madalina, apetrei}). Ignora middle-name irelevant: pastram
    toti tokenii, dar matching-ul cere doar un subset (vezi _name_hits)."""
    toks = set()
    for t in _WORD_SPLIT.split((emp.get("name") or "").lower()):
        if len(t) >= 3 and t not in _STOPNAME:
            toks.add(t)
    local = (emp.get("email") or "").split("@")[0].lower()
    for t in _WORD_SPLIT.split(local):
        if len(t) >= 3 and t not in _STOPNAME:
            toks.add(t)
    return toks


def _email_local_tokens(emp: Dict[str, Any]) -> set:
    local = (emp.get("email") or "").split("@")[0].lower()
    return {t for t in _WORD_SPLIT.split(local) if len(t) >= 3 and t not in _STOPNAME}


def _full_body(email: Dict[str, Any]) -> str:
    """Corpul COMPLET (text + html strip), inclusiv istoricul citat — acolo e semnatura
    agentului care a raspuns. Spre deosebire de _email_body (doar ultimul reply)."""
    bt = (email.get("body_text") or "")
    bh = email.get("body_html") or ""
    html_txt = ""
    try:
        html_txt = C._strip_html(bh)
    except Exception:
        html_txt = re.sub(r"<[^>]+>", " ", bh)
    return (bt + "\n" + html_txt)


def _has_reply_context(email: Dict[str, Any]) -> bool:
    """True daca emailul are istoric citat (e un reply pe un fir), nu un mail nou."""
    try:
        _, _, quoted_removed = _pd._new_content(email)
        return bool(quoted_removed)
    except Exception:
        return False


def _find_candidates(email: Dict[str, Any], employees: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Candidati = angajati identificati in corpul complet prin email-match (tare) sau
    name-match (fuzzy). Fiecare candidat: {id, name, email, department, source}."""
    body = _full_body(email)
    body_low = body.lower()
    found_emails = {m.group(0).lower() for m in _EMAIL_RE.finditer(body)}
    # tokeni-cuvant din body pentru name-match (whole-word)
    body_tokens = set(t for t in _WORD_SPLIT.split(body_low) if len(t) >= 3)

    cands: Dict[str, Dict[str, Any]] = {}
    for emp in employees:
        em = (emp.get("email") or "").lower()
        if not em:
            continue
        source = None
        # 1) email-match: adresa angajatului apare literal in fir.
        if em in found_emails:
            source = "email"
        else:
            # 2) name-match: tokenii din local-part (prenume+nume) apar TOTI ca whole-word,
            #    SAU cel putin 2 tokeni din nume (surname + un prenume). Cere >=2 tokeni
            #    pentru a evita false-positive pe un singur prenume comun.
            local_toks = _email_local_tokens(emp)
            name_toks = _name_tokens(emp)
            local_hit = bool(local_toks) and local_toks.issubset(body_tokens)
            name_hit = len([t for t in name_toks if t in body_tokens]) >= 2
            if local_hit or name_hit:
                source = "signature"
        if source:
            cands[em] = {"id": emp["id"], "name": emp.get("name"), "email": emp["email"],
                         "department": emp.get("department"), "source": source}
    # email-match e prioritar fata de signature la afisare/ordonare.
    ordered = sorted(cands.values(), key=lambda c: 0 if c["source"] == "email" else 1)
    return ordered


def _on_leave(employee_id: int, on_date) -> bool:
    """True daca angajatul are CONCEDIU (planned_leave) care acopera data emailului.
    Invoirile orare (leave_request, 3h/zi) NU blocheaza asignarea."""
    if not employee_id or not on_date:
        return False
    try:
        db = SessionLocal()
        row = db.execute(text(
            "SELECT 1 FROM employee_schedule WHERE employee_id=:id AND kind='planned_leave' "
            "AND start_date IS NOT NULL AND end_date IS NOT NULL "
            "AND :d BETWEEN start_date AND end_date "
            "AND COALESCE(lower(status),'') NOT IN ('rejected','refuzat','anulat','cancelled') "
            "LIMIT 1"), {"id": employee_id, "d": on_date}).fetchone()
        db.close()
        return bool(row)
    except Exception as e:
        logger.warning("_on_leave check failed emp=%s: %s", employee_id, e)
        return False


def _received_date(email: Dict[str, Any]):
    rv = email.get("received_at")
    if not rv:
        return None
    try:
        return str(rv)[:10]   # YYYY-MM-DD (cast ::date in query)
    except Exception:
        return None


def _none(reason: str, model: str = "none", **extra) -> Dict[str, Any]:
    out = {"assignee_email": None, "assignee_name": None, "assignee_id": None,
           "department": None, "confidence": None, "reason": reason, "model": model}
    out.update(extra)
    return out


def _resolve(emp: Dict[str, Any], confidence, reason: str, model: str,
             candidates: List[Dict[str, Any]], email: Dict[str, Any]) -> Dict[str, Any]:
    """Construieste rezultatul pentru un assignee ales, aplicand verificarea de concediu."""
    on_leave = _on_leave(emp.get("id"), _received_date(email))
    if on_leave:
        return _none(
            "Persoana identificata (" + (emp.get("name") or emp["email"]) + ") este in concediu la "
            "data emailului — lasat neasignat pentru review.",
            model="none",
            needs_review=True, on_leave=True, suggested_email=emp["email"],
            suggested_name=emp.get("name"),
            candidates=[c["email"] for c in candidates])
    return {"assignee_email": emp["email"], "assignee_name": emp.get("name"),
            "assignee_id": emp.get("id"), "department": emp.get("department"),
            "confidence": confidence, "reason": reason, "model": model,
            "candidates": [c["email"] for c in candidates]}


def classify_assignee(email: Dict[str, Any], attachments=None) -> Dict[str, Any]:
    """Asignare STRICTA pe utilizator. Intoarce mereu un dict; assignee_email=None = neasignat."""
    # 0) Gate context: mail nou / fara istoric citat -> nu avem sursa sigura.
    if not _has_reply_context(email):
        return _none("Email nou / fara reply — nicio sursa sigura de asignare.")

    body = _full_body(email)
    if CARGOTRACK_DOMAIN not in body.lower():
        return _none("Fara context CargoTrack in fir — neasignat.")

    employees = _load_employees()
    if not employees:
        return _none("Lista de utilizatori indisponibila — neasignat.", model="fallback")

    candidates = _find_candidates(email, employees)
    if not candidates:
        return _none("Niciun utilizator CargoTrack identificabil in fir — neasignat.")

    # 1) Un singur candidat -> asignare directa (subiect verificarii de concediu).
    if len(candidates) == 1:
        c = candidates[0]
        emp = next((e for e in employees if e["id"] == c["id"]), c)
        reason = ("Adresa " + c["email"] + " identificata in fir."
                  if c["source"] == "email"
                  else "Semnatura " + (c.get("name") or c["email"]) + " identificata in fir.")
        return _resolve(emp, 1.0, reason, c["source"], candidates, email)

    # 2) Mai multi candidati -> dezambiguizare AI (alege DOAR dintre ei, sau null).
    if not iris_ai.is_configured():
        # Fara AI: daca exista un singur candidat email-match, il preferam; altfel neasignat.
        email_matches = [c for c in candidates if c["source"] == "email"]
        if len(email_matches) == 1:
            c = email_matches[0]
            emp = next((e for e in employees if e["id"] == c["id"]), c)
            return _resolve(emp, 0.9, "Adresa " + c["email"] + " (unica adresa @cargotrack.ro de "
                            "angajat in fir).", "email", candidates, email)
        return _none("Mai multi candidati si AI indisponibil — neasignat pentru review.",
                     model="fallback", needs_review=True,
                     candidates=[c["email"] for c in candidates])

    dep = email.get("ai_department")
    content_body = C._email_body(email)
    content = ("Departament incadrat: " + str(dep or "?") + "\n\nMesaj (cu istoric):\n"
               + (body[:6000] if body else content_body))
    system = build_system_prompt(candidates)
    res = iris_ai.run_prompt(
        system, content, response_format="json", temperature=0.0, max_tokens=200,
        task="cargo360:email_assignee", email_id=email.get("id"),
        use_cache=True, learn=False)
    if not res.get("ok"):
        logger.warning("assignee disambiguation failed: %s", res.get("error"))
        return _none("Eroare AI la dezambiguizare — neasignat.", model="fallback",
                     needs_review=True, candidates=[c["email"] for c in candidates])
    parsed = res.get("parsed") if isinstance(res.get("parsed"), dict) else {}
    chosen = (parsed.get("assignee_email") or "").strip().lower() if parsed else ""
    valid = {c["email"].lower(): c for c in candidates}
    if not chosen or chosen == "null" or chosen not in valid:
        return _none("AI nu a putut alege cert responsabilul dintre candidati — neasignat.",
                     model="ai", needs_review=True, candidates=[c["email"] for c in candidates])
    c = valid[chosen]
    emp = next((e for e in employees if e["id"] == c["id"]), c)
    try:
        conf = float(parsed.get("confidence"))
        conf = max(0.0, min(1.0, conf))
    except (TypeError, ValueError):
        conf = None
    reason = (parsed.get("reason") or "").strip()[:400] or ("Ales de AI dintre candidatii din fir.")
    out = _resolve(emp, conf, reason, "ai", candidates, email)
    out["model_name"] = res.get("model")
    return out
