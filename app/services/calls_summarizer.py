"""Generare rezumat semantic per apel telefonic.

Rezumatul (`ai_summary`) capturează subiectul apelului și problema clientului în 1-2 fraze scurte,
indiferent de calitatea transcriptului. Folosit de calls_analyze pentru căutare semantică eficientă.

Funcții publice:
  summarize_call(call_id, db)            — generează/actualizează ai_summary pentru un apel
  backfill_recent(days, db, limit)       — backfill apeluri fără summary din ultimele N zile
  summarize_batch(call_ids, db)          — sumarizare în lot (intern)
"""

import json
import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import iris_ai

logger = logging.getLogger("mailguard.calls_summarizer")

BATCH_SIZE = 30
MAX_TRANSCRIPT_CHARS = 1200

SUMMARY_SYSTEM = """Ești un asistent care rezumă apeluri telefonice în română.

Din transcriptul de mai jos, extrage în maxim 2 fraze scurte:
1. Ce a vrut clientul / care era problema sau întrebarea lui principală
2. Cum s-a rezolvat (dacă se poate deduce)

Folosește limbaj simplu, păstrează termenii tehnici din transcript (ex: numele aplicațiilor, coduri de eroare, expresii exacte ale clientului).
Dacă transcriptul e incomprehensibil sau prea scurt, răspunde cu: "Apel neinteligibil."

Răspunde DOAR cu rezumatul — fără prefix, fără explicații extra."""


def summarize_call(call_id: int, db: Session) -> Optional[str]:
    """Generează ai_summary pentru un apel. Returnează summary-ul sau None la eroare."""
    row = db.execute(text(
        "SELECT transcript, ai_summary FROM calls WHERE id = :id"
    ), {"id": call_id}).fetchone()
    if not row:
        return None
    m = row._mapping
    if m.get("ai_summary"):
        return m["ai_summary"]
    transcript = (m.get("transcript") or "").strip()
    if not transcript:
        return None

    result = iris_ai.run_prompt(
        system=SUMMARY_SYSTEM,
        content=transcript[:MAX_TRANSCRIPT_CHARS],
        model_hint="haiku",
        temperature=0.1,
        max_tokens=200,
        task="cargo360:call_summary",
        no_cache=True,
    )
    if not result.get("ok"):
        logger.warning("summarize_call failed id=%s: %s", call_id, result.get("error"))
        return None

    summary = (result.get("text") or "").strip()
    if not summary:
        return None

    db.execute(text(
        "UPDATE calls SET ai_summary = :s, ai_summary_at = now() WHERE id = :id"
    ), {"s": summary, "id": call_id})
    db.commit()
    return summary


def summarize_batch(call_ids: list, db: Session) -> dict:
    """Sumarizează o listă de apeluri în loturi. Returnează {ok, done, errors}."""
    done = 0
    errors = 0
    for i in range(0, len(call_ids), BATCH_SIZE):
        batch = call_ids[i:i + BATCH_SIZE]
        rows = db.execute(text(
            "SELECT id, transcript FROM calls WHERE id = ANY(:ids) AND ai_summary IS NULL"
        ), {"ids": batch}).fetchall()

        if not rows:
            continue

        payload = [
            {"call_id": r._mapping["id"],
             "transcript": (r._mapping["transcript"] or "")[:MAX_TRANSCRIPT_CHARS]}
            for r in rows
        ]

        batch_system = """Ești un asistent care rezumă apeluri telefonice în română.
Pentru fiecare apel din lista JSON de mai jos, generează un rezumat de maxim 2 fraze: ce a vrut clientul și cum s-a rezolvat.
Păstrează termenii tehnici și expresiile exacte ale clientului.
Răspunde STRICT cu JSON valid:
{"summaries": [{"call_id": 123, "summary": "Rezumat scurt..."}]}
Apeluri incomprehensibile: {"call_id": 123, "summary": "Apel neinteligibil."}"""

        result = iris_ai.run_prompt(
            system=batch_system,
            content=json.dumps(payload, ensure_ascii=False),
            model_hint="haiku",
            response_format="json",
            temperature=0.1,
            max_tokens=len(payload) * 120,
            task="cargo360:call_summary_batch",
            no_cache=True,
        )
        if not result.get("ok"):
            logger.warning("summarize_batch lot %d eroare: %s", i, result.get("error"))
            errors += len(rows)
            continue

        parsed = result.get("parsed") or {}
        if isinstance(parsed, str):
            try:
                parsed = json.loads(parsed)
            except Exception:
                errors += len(rows)
                continue

        for item in parsed.get("summaries", []):
            cid = item.get("call_id")
            summary = (item.get("summary") or "").strip()
            if cid and summary:
                try:
                    db.execute(text(
                        "UPDATE calls SET ai_summary = :s, ai_summary_at = now() WHERE id = :id AND ai_summary IS NULL"
                    ), {"s": summary, "id": int(cid)})
                    done += 1
                except Exception:
                    errors += 1
        try:
            db.commit()
        except Exception as e:
            logger.error("summarize_batch commit failed: %s", e)
            db.rollback()
            errors += len(rows)

    return {"ok": True, "done": done, "errors": errors}


def backfill_recent(days: int, db: Session, limit: int = 2000) -> dict:
    """Generează ai_summary pentru apelurile fără summary din ultimele N zile."""
    rows = db.execute(text(
        """SELECT id FROM calls
           WHERE started_at >= now() - make_interval(days => :days)
             AND transcript IS NOT NULL AND transcript != ''
             AND ai_summary IS NULL
           ORDER BY started_at DESC
           LIMIT :limit"""
    ), {"days": days, "limit": limit}).fetchall()

    call_ids = [r._mapping["id"] for r in rows]
    if not call_ids:
        return {"ok": True, "done": 0, "errors": 0, "total": 0}

    result = summarize_batch(call_ids, db)
    result["total"] = len(call_ids)
    return result
