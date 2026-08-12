"""Analiză semantică apeluri — identificare apeluri relevante pentru un topic/problemă.

POST /api/v1/calls/analyze-topic
  Body: { query: str, days: int (1-90) }
  Folosește ai_summary (pre-generat cu Haiku) în loc de transcript brut.
  Cache 6h per (query_hash, days). Returnează cost_tokens în response.

POST /api/v1/calls/analyze-topic/backfill
  Declanșează generare ai_summary pentru ultimele N zile (default 4).
"""
import hashlib
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.v1.auth import get_current_admin
from app.services import iris_ai

logger = logging.getLogger("mailguard.calls_analyze")
router = APIRouter()

BATCH_SIZE = 40
MAX_SUMMARY_CHARS = 400
CACHE_HOURS = 6

SEARCH_SYSTEM = """Ești un analist care identifică apeluri telefonice relevante pentru o problemă dată.

SARCINA: Din lista de mai jos, identifică NUMAI apelurile în care clientul descrie sau raportează DIRECT această problemă:
"{query}"

Fiecare apel are un câmp "summary" — un rezumat scurt al conținutului apelului.

REGULI STRICTE:
1. Referința la problemă trebuie să fie CLARĂ în summary — nu asocieri vage sau tangențiale.
2. Ignoră apelurile unde problema e menționată doar de agent, nu de client.
3. Ignoră apelurile total irelevante sau cu summary "Apel neinteligibil."
4. Acceptă formulări colocviale și metafore dacă legătura cu problema e clară în context.

Răspunde EXCLUSIV cu JSON valid, fără text suplimentar:
{{"relevant": [{{"call_id": 123, "reason": "ce anume descrie clientul — max 100 caractere"}}]}}
Dacă niciun apel nu e relevant: {{"relevant": []}}"""


def _query_hash(query: str, days: int) -> str:
    return hashlib.sha256(f"{query.strip().lower()}|{days}".encode()).hexdigest()[:32]


def _get_cache(db: Session, query_hash: str, days: int):
    row = db.execute(text(
        "SELECT result_json, tokens_used, created_at FROM calls_analyze_cache "
        "WHERE query_hash = :h AND days = :d "
        "AND created_at > now() - make_interval(hours => :hrs) "
        "ORDER BY created_at DESC LIMIT 1"
    ), {"h": query_hash, "d": days, "hrs": CACHE_HOURS}).fetchone()
    return row._mapping if row else None


def _set_cache(db: Session, query_hash: str, query_text: str, days: int,
               result: dict, tokens_used: int) -> None:
    try:
        db.execute(text(
            "INSERT INTO calls_analyze_cache(query_hash, query_text, days, result_json, tokens_used) "
            "VALUES (:h, :qt, :d, CAST(:r AS jsonb), :t) "
            "ON CONFLICT (query_hash, days) DO UPDATE SET "
            "result_json = CAST(:r AS jsonb), tokens_used = :t, created_at = now(), query_text = :qt"
        ), {"h": query_hash, "qt": query_text, "d": days,
            "r": json.dumps(result, ensure_ascii=False, default=str), "t": tokens_used})
        db.commit()
    except Exception as e:
        logger.warning("cache write failed: %s", e)
        db.rollback()


@router.post("/calls/analyze-topic")
def analyze_topic(
    body: dict,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    query = (body.get("query") or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="'query' este obligatoriu")

    days = int(body.get("days") or 10)
    days = max(1, min(days, 90))

    query_hash = _query_hash(query, days)

    # Cache hit
    cached = _get_cache(db, query_hash, days)
    if cached:
        result = dict(cached["result_json"])
        result["cached"] = True
        result["cost_tokens"] = cached["tokens_used"]
        return result

    # Preia apeluri cu ai_summary din interval
    rows = db.execute(text("""
        SELECT c.id, c.started_at, c.ai_summary, c.transcript,
               c.client_id, c.caller_number,
               c.duration_seconds, c.ai_category, c.ai_tone,
               cl.name AS client_name
        FROM calls c
        LEFT JOIN clients cl ON cl.id = c.client_id
        WHERE c.started_at >= now() - make_interval(days => :days)
          AND c.transcript IS NOT NULL AND c.transcript != ''
        ORDER BY c.started_at DESC
        LIMIT 5000
    """), {"days": days}).fetchall()

    total_scanned = len(rows)
    if total_scanned == 0:
        return {"calls": [], "clients": [], "total_scanned": 0, "total_matched": 0,
                "query": query, "days": days, "cached": False, "cost_tokens": 0,
                "no_summary_count": 0}

    # Apeluri cu și fără summary
    with_summary = [r for r in rows if r._mapping.get("ai_summary")]
    without_summary = [r for r in rows if not r._mapping.get("ai_summary")]
    no_summary_count = len(without_summary)

    total_tokens = 0
    reasons_map: dict = {}

    # Procesare apeluri cu summary (Haiku, loturi de 40)
    if with_summary:
        for batch_start in range(0, len(with_summary), BATCH_SIZE):
            batch = with_summary[batch_start: batch_start + BATCH_SIZE]
            payload = [
                {"call_id": r._mapping["id"],
                 "summary": (r._mapping["ai_summary"] or "")[:MAX_SUMMARY_CHARS]}
                for r in batch
            ]
            system = SEARCH_SYSTEM.format(query=query)
            result = iris_ai.run_prompt(
                system=system,
                content=json.dumps(payload, ensure_ascii=False),
                model_hint="haiku",
                response_format="json",
                task="cargo360:topic_search",
                max_tokens=800,
                temperature=0.1,
                no_cache=True,
            )
            if not result.get("ok"):
                logger.warning("calls_analyze summary lot %d eroare: %s", batch_start, result.get("error"))
                continue
            usage = result.get("usage") or {}
            total_tokens += (usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0)
            parsed = result.get("parsed") or {}
            if not isinstance(parsed, dict):
                try:
                    parsed = json.loads(result.get("text", "{}"))
                except Exception:
                    continue
            for item in parsed.get("relevant", []):
                cid = item.get("call_id")
                reason = (item.get("reason") or "")[:120]
                if cid and reason:
                    reasons_map[int(cid)] = reason

    # Apeluri fără summary — fallback pe transcript (max 400 chars), loturi de 20
    if without_summary:
        fallback_batch_size = 20
        for batch_start in range(0, len(without_summary), fallback_batch_size):
            batch = without_summary[batch_start: batch_start + fallback_batch_size]
            payload = [
                {"call_id": r._mapping["id"],
                 "summary": (r._mapping["transcript"] or "")[:MAX_SUMMARY_CHARS]}
                for r in batch
            ]
            system = SEARCH_SYSTEM.format(query=query)
            result = iris_ai.run_prompt(
                system=system,
                content=json.dumps(payload, ensure_ascii=False),
                model_hint="haiku",
                response_format="json",
                task="cargo360:topic_search",
                max_tokens=600,
                temperature=0.1,
                no_cache=True,
            )
            if not result.get("ok"):
                continue
            usage = result.get("usage") or {}
            total_tokens += (usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0)
            parsed = result.get("parsed") or {}
            if not isinstance(parsed, dict):
                try:
                    parsed = json.loads(result.get("text", "{}"))
                except Exception:
                    continue
            for item in parsed.get("relevant", []):
                cid = item.get("call_id")
                reason = (item.get("reason") or "")[:120]
                if cid and reason:
                    reasons_map[int(cid)] = reason

    # Construiește rezultatul final
    rows_by_id = {r._mapping["id"]: r._mapping for r in rows}
    matched_calls = []
    clients_count: dict = {}

    for call_id, reason in reasons_map.items():
        r = rows_by_id.get(call_id)
        if not r:
            continue
        started_at = r["started_at"].isoformat() if r["started_at"] else None
        matched_calls.append({
            "id": r["id"],
            "started_at": started_at,
            "caller_number": r["caller_number"],
            "client_id": r["client_id"],
            "client_name": r["client_name"],
            "duration_seconds": r["duration_seconds"],
            "ai_category": r["ai_category"],
            "ai_tone": r["ai_tone"],
            "match_reason": reason,
        })
        if r["client_id"]:
            cid = r["client_id"]
            if cid not in clients_count:
                clients_count[cid] = {"client_id": cid, "client_name": r["client_name"], "call_count": 0}
            clients_count[cid]["call_count"] += 1

    matched_calls.sort(key=lambda x: x["started_at"] or "", reverse=True)
    clients_list = sorted(clients_count.values(), key=lambda x: x["call_count"], reverse=True)

    final = {
        "calls": matched_calls,
        "clients": clients_list,
        "total_scanned": total_scanned,
        "total_matched": len(matched_calls),
        "query": query,
        "days": days,
        "cached": False,
        "cost_tokens": total_tokens,
        "no_summary_count": no_summary_count,
    }

    _set_cache(db, query_hash, query, days, final, total_tokens)
    return final


@router.post("/calls/analyze-topic/backfill")
def backfill_summaries(
    body: dict,
    db: Session = Depends(get_db),
    _admin=Depends(get_current_admin),
):
    from app.services.calls_summarizer import backfill_recent
    days = int(body.get("days") or 4)
    days = max(1, min(days, 30))
    result = backfill_recent(days, db)
    return {"ok": True, "days": days, **result}
