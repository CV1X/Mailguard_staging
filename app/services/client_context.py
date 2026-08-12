"""Agregare context client (ultimele 5 zile) pentru imbogatire clasificare categorie."""

import logging
from datetime import datetime, timedelta, timezone
from app.services import iris_ai

logger = logging.getLogger(__name__)

_SUMMARY_SYSTEM = (
    "Ești un analist de relații cu clienții. Primești istoricul recent al unui client "
    "(mailuri, apeluri, task-uri din ultimele 5 zile) și produci un scurt summary structural.\n\n"
    "Răspunde EXCLUSIV cu un obiect JSON valid, fără text în afara JSON-ului:\n"
    '{\n'
    '  "context_general": "<1-2 propoziții despre natura interacțiunilor recente>",\n'
    '  "atitudine": "pozitiva" | "neutra" | "negativa" | "mixta",\n'
    '  "satisfactie": "ridicata" | "medie" | "scazuta" | "necunoscuta",\n'
    '  "nemultumire_principala": "<subiectul principal de nemulțumire, sau null dacă nu există>",\n'
    '  "numar_contacte": <int>,\n'
    '  "confidence": <float 0.0-1.0>\n'
    "}\n\n"
    "Dacă istoricul e gol sau insuficient, returnează:\n"
    '{"context_general": null, "atitudine": "necunoscuta", "satisfactie": "necunoscuta", '
    '"nemultumire_principala": null, "numar_contacte": 0, "confidence": 0.0}'
)

_EMPTY_SUMMARY = {
    "context_general": None,
    "atitudine": "necunoscuta",
    "satisfactie": "necunoscuta",
    "nemultumire_principala": None,
    "numar_contacte": 0,
    "confidence": 0.0,
}


def get_context_summary(context_payload: dict, email_id: int = None) -> dict:
    """
    Trimite payload-ul client_context la IRIS si obtine summary structurat.
    Fallback safe: orice eroare -> returneaza _EMPTY_SUMMARY, fara exceptie.
    """
    if not context_payload or not context_payload.get("client"):
        return _EMPTY_SUMMARY

    try:
        c = context_payload
        client_name = (c.get("client") or {}).get("name", "necunoscut")
        n_emails = len(c.get("emails", []))
        n_calls = len(c.get("calls", []))
        n_tasks = len(c.get("tasks", []))

        lines = [f"Client: {client_name} | Fereastră: {c.get('window_days', 5)} zile"]
        lines.append(f"Mailuri recente ({n_emails}):")
        for e in c.get("emails", [])[:10]:
            cat = e.get("ai_category") or "—"
            lines.append(f"  - [{cat}] {e.get('subject', '')} ({(e.get('received_at') or '')[:10]})")

        if n_calls:
            lines.append(f"\nApeluri ({n_calls}):")
            for call in c.get("calls", [])[:5]:
                tone = call.get("ai_tone") or "—"
                dur = call.get("duration_seconds") or 0
                lines.append(
                    f"  - [{tone}] {call.get('direction', '')} {dur}s"
                    f" ({(call.get('started_at') or '')[:10]})"
                )
                if call.get("transcript"):
                    lines.append(f"    Transcriere: {call['transcript'][:200]}")

        if n_tasks:
            lines.append(f"\nTask-uri ({n_tasks}):")
            for t in c.get("tasks", [])[:5]:
                lines.append(
                    f"  - [{t.get('status', '')}|{t.get('priority', '')}] {t.get('title', '')}"
                    f" ({(t.get('cts_created_at') or '')[:10]})"
                )

        content = "\n".join(lines)

        res = iris_ai.run_prompt(
            system=_SUMMARY_SYSTEM,
            content=content,
            response_format="json",
            task="cargo360:client_context_summary",
            timeout=30.0,
            max_tokens=300,
            email_id=email_id,
        )

        if res.get("ok") and isinstance(res.get("parsed"), dict):
            parsed = res["parsed"]
            if "atitudine" in parsed and "satisfactie" in parsed:
                return parsed

        logger.warning(
            "client_context: summary IRIS invalid sau ok=False pentru email_id=%s; error=%s",
            email_id, res.get("error"),
        )
        return _EMPTY_SUMMARY

    except Exception:
        logger.exception("client_context: eroare la get_context_summary pentru email_id=%s", email_id)
        return _EMPTY_SUMMARY

WINDOW_DAYS = 5


def get_client_context(from_address: str, now: datetime, cur) -> dict:
    """
    Rezolva clientul dupa from_address, colecteaza mailuri/apeluri/task-uri din ultimele
    WINDOW_DAYS zile. Returneaza payload unificat gata de trimis la IRIS (T2).
    Client nerezolvabil → payload gol, fara exceptie.
    """
    since = now - timedelta(days=WINDOW_DAYS)
    result = {"client": None, "emails": [], "calls": [], "tasks": [], "window_days": WINDOW_DAYS}

    try:
        # 1. Rezolva client din adresa expeditorului (GIN index pe clients.emails jsonb)
        cur.execute(
            "SELECT id, iris_client_id, name, phones FROM clients "
            "WHERE emails @> %s::jsonb AND is_active = TRUE LIMIT 1",
            (f'["{from_address}"]',)
        )
        row = cur.fetchone()
        if not row:
            return result

        client_id = row["id"]; iris_client_id = row["iris_client_id"]
        client_name = row["name"]; phones = row["phones"]
        result["client"] = {"id": client_id, "iris_client_id": iris_client_id, "name": client_name}

        # 2. Mailuri din ultimele 5 zile de la acelasi expeditor
        cur.execute(
            """SELECT id, subject, from_address, received_at, ai_category, ai_department
               FROM emails
               WHERE from_address = %s AND received_at >= %s
               ORDER BY received_at DESC LIMIT 20""",
            (from_address, since)
        )
        result["emails"] = [
            {
                "id": r["id"], "subject": r["subject"], "from_address": r["from_address"],
                "received_at": r["received_at"].isoformat() if r["received_at"] else None,
                "ai_category": r["ai_category"], "ai_department": r["ai_department"]
            }
            for r in cur.fetchall()
        ]

        # 3. Apeluri din ultimele 5 zile (doar daca clientul are telefon asociat)
        phone_list = phones if isinstance(phones, list) else []
        if phone_list:
            cur.execute(
                """SELECT id, direction, caller_number, started_at, duration_seconds,
                          ai_category, ai_tone, transcript
                   FROM calls
                   WHERE client_id = %s AND started_at >= %s
                   ORDER BY started_at DESC LIMIT 10""",
                (client_id, since)
            )
            result["calls"] = [
                {
                    "id": r["id"], "direction": r["direction"], "caller_number": r["caller_number"],
                    "started_at": r["started_at"].isoformat() if r["started_at"] else None,
                    "duration_seconds": r["duration_seconds"], "ai_category": r["ai_category"],
                    "ai_tone": r["ai_tone"],
                    "transcript": (r["transcript"] or "")[:500] if r["transcript"] else None
                }
                for r in cur.fetchall()
            ]

        # 4. Task-uri din ultimele 5 zile
        # NOTA: cts_task_ground_truth.client_id = clients.iris_client_id (nu clients.id)
        if iris_client_id:
            cur.execute(
                """SELECT id, iris_task_id, task_type, status, priority, title, description,
                          department, cts_created_at
                   FROM cts_task_ground_truth
                   WHERE client_id = %s AND cts_created_at >= %s
                   ORDER BY cts_created_at DESC LIMIT 10""",
                (iris_client_id, since)
            )
            result["tasks"] = [
                {
                    "id": r["id"], "iris_task_id": r["iris_task_id"], "task_type": r["task_type"],
                    "status": r["status"], "priority": r["priority"], "title": r["title"],
                    "description": (r["description"] or "")[:300] if r["description"] else None,
                    "department": r["department"],
                    "cts_created_at": r["cts_created_at"].isoformat() if r["cts_created_at"] else None
                }
                for r in cur.fetchall()
            ]

    except Exception:
        logger.exception("client_context: eroare la agregare pentru %s", from_address)
        return {"client": None, "emails": [], "calls": [], "tasks": [], "window_days": WINDOW_DAYS}

    return result
