"""T5: Endpoint extern satisfacție clienți — consum de aplicații terțe (ex. marketing).

Auth: X-API-Key header (SHA-256 hash verificat în tabel api_keys).
Rate limit: 60 req/min per API key (sliding window in-process).
Guvernanță: expune EXCLUSIV grad + lună + client_id — fără conținut conversații.

Endpoint:
  GET /ext/v1/satisfaction?from_month=YYYY-MM&to_month=YYYY-MM&min_pct=0&max_pct=100&client_id=...&limit=200&offset=0

Migrație necesară: api_keys.scope (opțional — skip dacă nu e prezentă, accesul e per key activ).
"""

import collections
import hashlib
import logging
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.orm import Session
from fastapi import Depends

from app.database import get_db

logger = logging.getLogger("mailguard.satisfaction_api")
router = APIRouter()

# ── Rate limiting (sliding window 60s, 60 req per key) ───────────────────────
_RL_WINDOW = 60       # secunde
_RL_MAX    = 60       # requesturi per fereastră
_rl_store: dict = collections.defaultdict(list)   # key_hash -> [timestamp, ...]


def _rate_limit(key_hash: str) -> bool:
    """True dacă requestul este permis; False dacă e depășit limita."""
    now = time.time()
    cutoff = now - _RL_WINDOW
    timestamps = [t for t in _rl_store[key_hash] if t > cutoff]
    if len(timestamps) >= _RL_MAX:
        return False
    timestamps.append(now)
    _rl_store[key_hash] = timestamps
    return True


# ── Auth ──────────────────────────────────────────────────────────────────────

def _verify_api_key(request: Request, db: Session) -> str:
    """Verifică X-API-Key, aplică rate limit. Returnează label-ul key-ului sau aruncă 401/429."""
    raw_key = request.headers.get("X-API-Key", "").strip()
    if not raw_key:
        raise HTTPException(401, detail="X-API-Key lipsă")
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    row = db.execute(
        text("SELECT label FROM api_keys WHERE key_hash=:h AND is_active=true"),
        {"h": key_hash},
    ).first()
    if not row:
        raise HTTPException(401, detail="X-API-Key invalid sau inactiv")
    if not _rate_limit(key_hash):
        raise HTTPException(429, detail="Rate limit depășit — max 60 req/min per cheie")
    return row[0]


# ── Endpoint principal ────────────────────────────────────────────────────────

@router.get("/ext/v1/satisfaction")
def get_satisfaction_external(
    request: Request,
    from_month: Optional[str] = Query(default=None, description="YYYY-MM — luna de start (inclusiv)"),
    to_month:   Optional[str] = Query(default=None, description="YYYY-MM — luna de final (inclusiv)"),
    client_id:  Optional[int] = Query(default=None, description="Filtrare per ID client"),
    min_pct:    Optional[float] = Query(default=None, ge=0, le=100, description="Filtrare min satisfacție"),
    max_pct:    Optional[float] = Query(default=None, ge=0, le=100, description="Filtrare max satisfacție"),
    limit:      int = Query(default=200, ge=1, le=1000),
    offset:     int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """
    Returnează istoricul de satisfacție per client, per lună.

    Câmpuri returnate (NUMAI):
      - client_id, month_key, satisfaction_pct, is_unsatisfied, carry_forward

    Niciun câmp din mailuri, apeluri sau task-uri nu este expus.

    Autentificare: header `X-API-Key: <cheie>`
    Rate limit: 60 req/min per cheie

    Exemple:
      GET /ext/v1/satisfaction                          — ultimele 12 luni, toți clienții
      GET /ext/v1/satisfaction?from_month=2026-01&to_month=2026-06  — interval specific
      GET /ext/v1/satisfaction?max_pct=59               — numai clienți nesatisfăcuți
      GET /ext/v1/satisfaction?client_id=4088           — un singur client

    Răspuns:
      {
        "ok": true,
        "total": 1382,
        "limit": 200,
        "offset": 0,
        "items": [
          { "client_id": 4088, "month_key": "2026-07", "satisfaction_pct": 60.7,
            "is_unsatisfied": false, "carry_forward": false }
        ]
      }

    Erori:
      401 — cheie lipsă sau invalidă
      429 — prea multe requesturi (max 60/min)
      400 — parametri invalizi
    """
    _verify_api_key(request, db)

    # Validare interval luni
    import re
    for m_param, m_name in [(from_month, "from_month"), (to_month, "to_month")]:
        if m_param and not re.match(r"^\d{4}-\d{2}$", m_param):
            raise HTTPException(400, detail=f"{m_name} trebuie să fie format YYYY-MM")

    # Default from_month = ultima 12 luni dacă nu e specificat
    if not from_month and not to_month:
        from_month = None  # lăsăm DB să decidă prin ORDER DESC + LIMIT

    conditions = ["s.satisfaction_pct IS NOT NULL"]
    params: dict = {"limit": limit, "offset": offset}

    if from_month:
        conditions.append("s.month_key >= :fm")
        params["fm"] = from_month
    if to_month:
        conditions.append("s.month_key <= :tm")
        params["tm"] = to_month
    if client_id is not None:
        conditions.append("s.client_id = :cid")
        params["cid"] = client_id
    if min_pct is not None:
        conditions.append("s.satisfaction_pct >= :minp")
        params["minp"] = min_pct
    if max_pct is not None:
        conditions.append("s.satisfaction_pct <= :maxp")
        params["maxp"] = max_pct

    where = " AND ".join(conditions)

    count_row = db.execute(text(f"""
        SELECT COUNT(*) FROM client_satisfaction_snapshots s WHERE {where}
    """), params).fetchone()
    total = count_row[0] if count_row else 0

    rows = db.execute(text(f"""
        SELECT s.client_id, s.month_key, s.satisfaction_pct, s.is_unsatisfied, s.carry_forward
        FROM client_satisfaction_snapshots s
        WHERE {where}
        ORDER BY s.month_key DESC, s.client_id ASC
        LIMIT :limit OFFSET :offset
    """), params).fetchall()

    return {
        "ok": True,
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "client_id": r[0],
                "month_key": r[1],
                "satisfaction_pct": float(r[2]) if r[2] is not None else None,
                "is_unsatisfied": r[3],
                "carry_forward": r[4],
            }
            for r in rows
        ],
    }
