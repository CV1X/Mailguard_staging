"""Analiză LLM per interacțiune client (email + call) — Nivelul 1 din sistemul v2.

Produce un JSON structurat cu semnale de satisfacție per interacțiune și îl salvează
în tabelul `interaction_analysis`. Idempotent: aceeași interacțiune cu același model_version
nu se re-analizează.

Câmpuri produse (conform spec customer health score):
  sentiment, emotional_intensity, emotions, problem_related, problem_description,
  is_repeat_issue, effort_signals, resolution_signal, formality_level, message_warmth,
  future_orientation, asks_questions, red_flags, praise_flags, summary, confidence

Extra pentru apeluri: client_talk_ratio, interruptions_or_tension, call_outcome, promises_made

Utilizare:
  from app.services.interaction_analyzer import analyze_email, analyze_call, process_batch
  result = analyze_email(email_id, cur, conn)
"""

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from app.services import iris_ai

logger = logging.getLogger("mailguard.interaction_analyzer")

# Model folosit pentru analiză (gemma = local vLLM, ieftin, fără cost API extern)
_MODEL = "gemma"

# Versiunea promptului — schimbă pentru a forța re-analizarea tuturor interacțiunilor
_PROMPT_VERSION = "v1.1"

# Lungime maximă text trimis la LLM
_MAX_CHARS = 3000
_KEEP_START = 1800
_KEEP_END = 1000

# Câmpuri obligatorii în răspunsul JSON
_REQUIRED_FIELDS = {
    "sentiment", "emotional_intensity", "emotions", "problem_related",
    "is_repeat_issue", "effort_signals", "resolution_signal",
    "formality_level", "message_warmth", "future_orientation",
    "asks_questions", "red_flags", "praise_flags", "summary", "confidence",
}

_VALID_RED_FLAGS = {
    "mentiune_reziliere", "mentiune_concurenta", "mentiune_penalitati_contract",
    "escaladare_management", "cerere_export_date", "amenintare_legala", "ultimatum",
}
_VALID_PRAISE_FLAGS = {
    "lauda_explicita", "recomandare_altora", "multumire_persoana_anume", "extindere_servicii",
}

_SYSTEM_EMAIL = """Ești psiholog și analist de business specializat în relații B2B. \
Analizezi un email dintr-o conversație între compania noastră (servicii de monitorizare flote / logistică) \
și un client. Textele pot fi în română sau engleză.

Returnează STRICT un JSON valid cu această structură, fără alt text:

{
  "sentiment": <float -1.0..1.0, valența emoțională a EXPEDITORULUI>,
  "emotional_intensity": <float 0..1, cât de încărcat emoțional e mesajul>,
  "emotions": [<max 3 dintre: "frustrare","furie","dezamagire","ingrijorare","neutru","multumire","entuziasm","recunostinta">],
  "problem_related": <bool, mesajul semnalează o problemă/defecțiune/eroare?>,
  "problem_description": <string scurt sau null>,
  "is_repeat_issue": <bool, clientul indică că a mai semnalat această problemă? (ex: "revin", "v-am mai scris", "încă aștept", "a doua oară")>,
  "effort_signals": <int 0..3, câte semnale de efort conține: follow-up nesolicitat, cerere repetată, exasperare procedurală>,
  "resolution_signal": <"rezolvat" | "in_lucru" | "nerezolvat" | "n/a">,
  "formality_level": <float 0..1, 0=foarte informal/prietenos, 1=foarte formal/distant>,
  "message_warmth": <float 0..1, căldura relațională: salutări personale, mulțumiri, small talk>,
  "future_orientation": <bool, menționează planuri viitoare, extinderi, colaborare pe termen lung?>,
  "asks_questions": <bool, clientul pune întrebări de interes/curiozitate (nu reclamații)?>,
  "red_flags": [<oricare dintre: "mentiune_reziliere","mentiune_concurenta","mentiune_penalitati_contract","escaladare_management","cerere_export_date","amenintare_legala","ultimatum">],
  "praise_flags": [<oricare dintre: "lauda_explicita","recomandare_altora","multumire_persoana_anume","extindere_servicii">],
  "summary": <string, max 2 propoziții, în română>,
  "confidence": <float 0..1, cât de sigură e analiza>,
  "message_length_signal": <float 0..1, 0=foarte scurt/monosilabic (sub 3 cuvinte), 0.5=mediu, 1=elaborat/detaliat (peste 100 cuvinte)>,
  "initiative": <"client_initiated" | "response_to_us" | "follow_up" — client_initiated=primul contact pe un subiect nou, response_to_us=răspunde la un email al nostru, follow_up=revine cu aceași problemă>
}

Reguli:
- Pentru emailurile TRIMISE de noi către client (direction=outbound): evaluează doar tonul nostru și dacă promitem ceva. Sentimentul CLIENTULUI nu se deduce din mesajele noastre — pune sentiment=0.0, confidence=0.3.
- Nu confunda politețea cu satisfacția: un mesaj politicos dar rece și scurt de la un client anterior călduros e un semnal negativ (formality ↑, warmth ↓).
- Emailurile automate (notificări, facturi, out-of-office) → confidence: 0.1 și valori neutre.
- Nu confunda furia pe o PROBLEMĂ cu nemulțumirea față de COMPANIE — dacă clientul e furios pe defecțiune dar cooperant cu noi, red_flags rămâne gol.
- MOTIVE ECONOMICE / EXTERNE — NU pui "mentiune_reziliere" (nici alt red_flag) dacă încetarea, suspendarea sau
  reducerea contractului are cauză economică sau externă, fără legătură cu calitatea serviciilor noastre:
  insolvență, faliment, executare silită, lipsă de bani/lichiditate, neplată, vânzarea firmei, schimbare de
  acționariat, închiderea activității, vânzarea sau reducerea flotei de camioane, accident/daună totală/furt,
  vehicul imobilizat, încheierea unui leasing sau a unei curse punctuale, restructurare, sezonalitate.
  Acestea NU sunt semnale de nemulțumire → red_flags rămâne gol, iar în `summary` notezi cauza reală (economică).
  Pui "mentiune_reziliere" DOAR când clientul leagă explicit plecarea de nemulțumirea față de serviciile noastre.
- Analizează în context relațional B2B logistică: un email de o propoziție de la un director de flotă e tipic, nu monosilabic îngrijorător. Calibrează la registrul profesional al domeniului."""

_SYSTEM_CALL = """Ești psiholog și analist de business specializat în relații B2B. \
Analizezi transcrierea unui apel telefonic între compania noastră (servicii de monitorizare flote / logistică) \
și un client. Textele pot fi în română sau engleză.

Returnează STRICT un JSON valid cu această structură, fără alt text:

{
  "sentiment": <float -1.0..1.0, valența emoțională a CLIENTULUI>,
  "emotional_intensity": <float 0..1, cât de încărcat emoțional e apelul>,
  "emotions": [<max 3 dintre: "frustrare","furie","dezamagire","ingrijorare","neutru","multumire","entuziasm","recunostinta">],
  "problem_related": <bool, apelul semnalează o problemă/defecțiune/eroare?>,
  "problem_description": <string scurt sau null>,
  "is_repeat_issue": <bool, clientul indică că a mai semnalat această problemă?>,
  "effort_signals": <int 0..3>,
  "resolution_signal": <"rezolvat_pe_loc" | "promisiune_follow_up" | "nerezolvat" | "informativ">,
  "formality_level": <float 0..1>,
  "message_warmth": <float 0..1>,
  "future_orientation": <bool>,
  "asks_questions": <bool>,
  "red_flags": [<oricare dintre: "mentiune_reziliere","mentiune_concurenta","mentiune_penalitati_contract","escaladare_management","cerere_export_date","amenintare_legala","ultimatum">],
  "praise_flags": [<oricare dintre: "lauda_explicita","recomandare_altora","multumire_persoana_anume","extindere_servicii">],
  "summary": <string, max 2 propoziții, în română>,
  "confidence": <float 0..1>,
  "client_talk_ratio": <float 0..1, estimare cât din conversație vorbește clientul>,
  "interruptions_or_tension": <bool, întreruperi, ton ridicat, sarcasm detectabil în transcript>,
  "call_outcome": <"rezolvat_pe_loc" | "promisiune_follow_up" | "nerezolvat" | "informativ">,
  "promises_made": [{"what": <string>, "deadline_mentioned": <string|null>}],
  "message_length_signal": <float 0..1, 0=client vorbește monosilabic/scurt (<5 schimburi), 1=dialog elaborat și implicat>,
  "initiative": <"client_initiated" | "response_to_us" | "follow_up">
}

Apelurile sunt natural mai emoționale decât emailurile — calibrează sentimentul la contextul vorbit, \
nu penaliza exprimarea colocvială.
MOTIVE ECONOMICE / EXTERNE — NU pui "mentiune_reziliere" (nici alt red_flag) dacă clientul cere încetarea,
suspendarea sau reducerea contractului din motive fără legătură cu calitatea serviciilor noastre: insolvență,
faliment, executare silită, lipsă de bani/lichiditate, neplată, vânzarea firmei, schimbare de acționariat,
închiderea activității, vânzarea sau reducerea flotei de camioane, accident/daună totală/furt, vehicul
imobilizat, încheierea unui leasing sau a unei curse punctuale, restructurare, sezonalitate.
Acestea NU înseamnă nemulțumire → red_flags rămâne gol, iar cauza reală (economică) se notează în `summary`.
Pui "mentiune_reziliere" DOAR când clientul leagă explicit plecarea de nemulțumirea față de serviciile noastre.
Analizează în context relațional B2B logistică: un apel scurt de confirmare e tipic și pozitiv, nu dezangajare."""


def _model_version() -> str:
    """SHA1 scurt al promptului + versiunea hardcodata. Schimbarea promptului → re-analiză automată."""
    h = hashlib.sha1((_SYSTEM_EMAIL + _SYSTEM_CALL + _PROMPT_VERSION).encode()).hexdigest()
    return h[:12]


def _truncate(text: str) -> str:
    """Trunchiată inteligent la _MAX_CHARS: primele _KEEP_START + ultimele _KEEP_END caractere."""
    if not text or len(text) <= _MAX_CHARS:
        return text or ""
    return text[:_KEEP_START] + "\n[... conținut trunchiat ...]\n" + text[-_KEEP_END:]


def _validate(parsed: dict, interaction_type: str) -> dict:
    """Validează și sanitizează răspunsul JSON de la LLM. Completează câmpurile lipsă cu valori safe."""
    result = {}
    result["sentiment"] = float(max(-1.0, min(1.0, parsed.get("sentiment", 0.0) or 0.0)))
    result["emotional_intensity"] = float(max(0.0, min(1.0, parsed.get("emotional_intensity", 0.5) or 0.5)))
    result["emotions"] = [e for e in (parsed.get("emotions") or []) if isinstance(e, str)][:3]
    result["problem_related"] = bool(parsed.get("problem_related", False))
    result["problem_description"] = str(parsed.get("problem_description") or "")[:200] or None
    result["is_repeat_issue"] = bool(parsed.get("is_repeat_issue", False))
    result["effort_signals"] = int(max(0, min(3, parsed.get("effort_signals", 0) or 0)))
    result["resolution_signal"] = parsed.get("resolution_signal", "n/a")
    result["formality_level"] = float(max(0.0, min(1.0, parsed.get("formality_level", 0.5) or 0.5)))
    result["message_warmth"] = float(max(0.0, min(1.0, parsed.get("message_warmth", 0.5) or 0.5)))
    result["future_orientation"] = bool(parsed.get("future_orientation", False))
    result["asks_questions"] = bool(parsed.get("asks_questions", False))
    result["red_flags"] = [f for f in (parsed.get("red_flags") or []) if f in _VALID_RED_FLAGS]
    result["praise_flags"] = [f for f in (parsed.get("praise_flags") or []) if f in _VALID_PRAISE_FLAGS]
    result["summary"] = str(parsed.get("summary") or "")[:500]
    result["confidence"] = float(max(0.0, min(1.0, parsed.get("confidence", 0.5) or 0.5)))
    result["message_length_signal"] = float(max(0.0, min(1.0, parsed.get("message_length_signal", 0.5) or 0.5)))
    result["initiative"] = parsed.get("initiative", "client_initiated") if parsed.get("initiative") in ("client_initiated", "response_to_us", "follow_up") else "client_initiated"

    if "call" in interaction_type:
        result["client_talk_ratio"] = float(max(0.0, min(1.0, parsed.get("client_talk_ratio", 0.5) or 0.5)))
        result["interruptions_or_tension"] = bool(parsed.get("interruptions_or_tension", False))
        result["call_outcome"] = parsed.get("call_outcome", "informativ")
        result["promises_made"] = (parsed.get("promises_made") or [])[:10]

    return result


def _call_llm(system_prompt: str, transcript: str) -> Optional[dict]:
    """Apelează IRIS AI gateway și returnează JSON parsed, sau None la eșec."""
    if not iris_ai.is_configured():
        logger.warning("interaction_analyzer: iris_ai not configured")
        return None

    res = iris_ai.run_prompt(
        system=system_prompt,
        content=transcript,
        response_format="json",
        model_hint=_MODEL,
        temperature=0.1,
        max_tokens=800,
        client="Cargo360-HealthScore",
    )
    if not res or not res.get("ok"):
        err = (res or {}).get("error", {})
        logger.warning("interaction_analyzer: LLM error: %s", err)
        return None

    parsed = res.get("parsed")
    if isinstance(parsed, dict):
        return parsed

    raw = res.get("text", "")
    try:
        return json.loads(raw)
    except Exception:
        logger.warning("interaction_analyzer: JSON parse failed on raw: %s", raw[:200])
        return None


def _save(cur, conn, client_id: int, interaction_type: str, interaction_id: int,
          occurred_at: datetime, direction: str, analysis: dict, mv: str) -> bool:
    """Inserează în interaction_analysis. ON CONFLICT DO NOTHING (idempotent)."""
    sentiment = analysis.get("sentiment")
    effort = analysis.get("effort_signals")
    red_flags = analysis.get("red_flags") or []

    try:
        cur.execute(
            """
            INSERT INTO interaction_analysis
                (client_id, interaction_type, interaction_id, occurred_at, direction,
                 analysis_json, sentiment_score, effort_signals, red_flags, model_version)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (interaction_type, interaction_id, model_version) DO NOTHING
            """,
            (
                client_id, interaction_type, interaction_id, occurred_at, direction,
                json.dumps(analysis), sentiment, effort,
                red_flags if red_flags else None,
                mv,
            ),
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        logger.error("interaction_analyzer: DB insert failed for %s id=%s", interaction_type, interaction_id, exc_info=True)
        return False


def _already_analyzed(cur, interaction_type: str, interaction_id: int, mv: str) -> bool:
    cur.execute(
        "SELECT 1 FROM interaction_analysis WHERE interaction_type=%s AND interaction_id=%s AND model_version=%s LIMIT 1",
        (interaction_type, interaction_id, mv),
    )
    return cur.fetchone() is not None


def analyze_email(email_id: int, cur, conn) -> Optional[dict]:
    """Analizează un email și salvează rezultatul. Returnează analysis dict sau None."""
    mv = _model_version()
    if _already_analyzed(cur, "email_in", email_id, mv):
        return None  # deja procesat cu această versiune

    try:
        cur.execute(
            """
            SELECT e.client_id, e.received_at, e.sent_to_cts_at,
                   e.body_text, e.subject, e.from_address,
                   e.ai_category, e.status
            FROM emails e
            WHERE e.id = %s
            """,
            (email_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
    except Exception:
        logger.error("analyze_email: DB read error for email_id=%s", email_id, exc_info=True)
        return None

    if hasattr(row, "keys"):
        client_id = row["client_id"]
        received_at = row["received_at"]
        body = row["body_text"] or ""
        subject = row["subject"] or ""
        from_addr = row["from_address"] or ""
        ai_category = row["ai_category"] or ""
        status = row["status"] or ""
    else:
        client_id, received_at, _, body, subject, from_addr, ai_category, status = row

    if not client_id:
        return None

    # Emailurile spam/quarantine nu se analizează
    if status in ("spam", "quarantined", "quarantined_strict"):
        return None

    direction = "inbound"
    interaction_type = "email_in"

    text_for_llm = _truncate(f"SUBIECT: {subject}\n\nCORPS:\n{body}")

    context = f"Email {'primit de la client' if direction == 'inbound' else 'trimis către client'}."
    if ai_category:
        context += f" Categorie pre-clasificată: {ai_category}."

    transcript = f"{context}\n\n{text_for_llm}"
    parsed = _call_llm(_SYSTEM_EMAIL, transcript)

    if parsed is None:
        return None

    analysis = _validate(parsed, interaction_type)
    occurred_at = received_at or datetime.now(timezone.utc)
    _save(cur, conn, client_id, interaction_type, email_id, occurred_at, direction, analysis, mv)
    return analysis


def analyze_call(call_id: int, cur, conn) -> Optional[dict]:
    """Analizează un apel și salvează rezultatul. Returnează analysis dict sau None."""
    mv = _model_version()
    if _already_analyzed(cur, "call_in", call_id, mv):
        return None

    try:
        cur.execute(
            """
            SELECT c.client_id, c.started_at, c.transcript, c.direction,
                   c.ai_tone, c.ai_category
            FROM calls c
            WHERE c.id = %s
            """,
            (call_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
    except Exception:
        logger.error("analyze_call: DB read error for call_id=%s", call_id, exc_info=True)
        return None

    if hasattr(row, "keys"):
        client_id = row["client_id"]
        started_at = row["started_at"]
        transcript_text = row["transcript"] or ""
        direction = row["direction"] or "inbound"
        ai_tone = row["ai_tone"] or ""
        ai_category = row["ai_category"] or ""
    else:
        client_id, started_at, transcript_text, direction, ai_tone, ai_category = row

    if not client_id or not transcript_text.strip():
        return None

    interaction_type = "call_in" if direction == "inbound" else "call_out"
    text_for_llm = _truncate(transcript_text)

    context = f"Apel telefonic {'primit de la client' if direction == 'inbound' else 'efectuat către client'}."
    if ai_tone:
        context += f" Ton pre-clasificat: {ai_tone}."
    if ai_category:
        context += f" Categorie: {ai_category}."

    transcript = f"{context}\n\nTRANSCRIPT:\n{text_for_llm}"
    parsed = _call_llm(_SYSTEM_CALL, transcript)

    if parsed is None:
        return None

    analysis = _validate(parsed, interaction_type)
    occurred_at = started_at or datetime.now(timezone.utc)
    if hasattr(occurred_at, "tzinfo") and occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=timezone.utc)

    _save(cur, conn, client_id, interaction_type, call_id, occurred_at, direction, analysis, mv)
    return analysis


def process_batch(cur, conn, client_ids: list = None, limit_emails: int = 200, limit_calls: int = 100) -> dict:
    """Procesează un batch de emailuri și apeluri neanalzate (sau pentru client_ids specificați).

    Returnează statistici: {emails_analyzed, calls_analyzed, skipped, errors}.
    """
    mv = _model_version()
    stats = {"emails_analyzed": 0, "calls_analyzed": 0, "skipped": 0, "errors": 0}

    # Emailuri inbound neanalzate
    try:
        if client_ids:
            cur.execute(
                """
                SELECT e.id FROM emails e
                WHERE e.client_id = ANY(%s)
                  AND e.status NOT IN ('spam','quarantined','quarantined_strict')
                  AND e.body_text IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1 FROM interaction_analysis ia
                    WHERE ia.interaction_type IN ('email_in','email_out')
                      AND ia.interaction_id = e.id
                      AND ia.model_version = %s
                  )
                ORDER BY e.received_at DESC
                LIMIT %s
                """,
                (client_ids, mv, limit_emails),
            )
        else:
            cur.execute(
                """
                SELECT e.id FROM emails e
                WHERE e.status NOT IN ('spam','quarantined','quarantined_strict')
                  AND e.body_text IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1 FROM interaction_analysis ia
                    WHERE ia.interaction_type IN ('email_in','email_out')
                      AND ia.interaction_id = e.id
                      AND ia.model_version = %s
                  )
                ORDER BY e.received_at DESC
                LIMIT %s
                """,
                (mv, limit_emails),
            )
        email_ids = [r[0] if not hasattr(r, "keys") else r["id"] for r in cur.fetchall()]
    except Exception:
        logger.error("process_batch: failed to fetch email ids", exc_info=True)
        email_ids = []

    for eid in email_ids:
        try:
            result = analyze_email(eid, cur, conn)
            if result is None:
                stats["skipped"] += 1
            else:
                stats["emails_analyzed"] += 1
        except Exception:
            logger.error("process_batch: error analyzing email %s", eid, exc_info=True)
            stats["errors"] += 1

    # Apeluri cu transcript neanalzate
    try:
        if client_ids:
            cur.execute(
                """
                SELECT c.id FROM calls c
                WHERE c.client_id = ANY(%s)
                  AND c.transcript IS NOT NULL AND c.transcript != ''
                  AND NOT EXISTS (
                    SELECT 1 FROM interaction_analysis ia
                    WHERE ia.interaction_type IN ('call_in','call_out')
                      AND ia.interaction_id = c.id
                      AND ia.model_version = %s
                  )
                ORDER BY c.started_at DESC
                LIMIT %s
                """,
                (client_ids, mv, limit_calls),
            )
        else:
            cur.execute(
                """
                SELECT c.id FROM calls c
                WHERE c.transcript IS NOT NULL AND c.transcript != ''
                  AND NOT EXISTS (
                    SELECT 1 FROM interaction_analysis ia
                    WHERE ia.interaction_type IN ('call_in','call_out')
                      AND ia.interaction_id = c.id
                      AND ia.model_version = %s
                  )
                ORDER BY c.started_at DESC
                LIMIT %s
                """,
                (mv, limit_calls),
            )
        call_ids = [r[0] if not hasattr(r, "keys") else r["id"] for r in cur.fetchall()]
    except Exception:
        logger.error("process_batch: failed to fetch call ids", exc_info=True)
        call_ids = []

    for cid in call_ids:
        try:
            result = analyze_call(cid, cur, conn)
            if result is None:
                stats["skipped"] += 1
            else:
                stats["calls_analyzed"] += 1
        except Exception:
            logger.error("process_batch: error analyzing call %s", cid, exc_info=True)
            stats["errors"] += 1

    return stats
