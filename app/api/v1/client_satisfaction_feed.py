"""Feed extern — satisfacție clienți, grupată PE CLIENT (un obiect per client).

Diferit de `/ext/v1/satisfaction` (app/api/v1/satisfaction_api.py), care întoarce rânduri
PLATE (un rând per client × lună). Aici forma e orientată pe client: media generală +
istoricul lunar înăuntru, plus datele de identificare (nume, CUI, id IRIS) — ca aplicațiile
externe să poată face potrivire după CUI/nume fără un al doilea apel.

Model de referință pentru contract/auth/logare: `/api/v1/cts/get_emails` (app/api/v1/cts.py).

Endpoint:
  GET /api/v1/ext/clients/satisfaction

Reguli de business (decise 2026-08-03):
  - Sunt returnați TOȚI clienții activi (~15.7k), nu doar cei cu snapshot de satisfacție.
  - Client FĂRĂ niciun snapshot -> `client_satisfactie = 100.0`, `istoric_satisfactie = {}`,
    `are_scor_calculat = false`. Presupunerea de business: „fără semnal negativ = client mulțumit".
  - Media generală se calculează DOAR peste lunile care au scor real. Lunile fără snapshot NU
    sunt completate cu 100 — altfel o lună slabă ar fi diluată artificial de luni inexistente.
  - Clienții marcați `satisfaction_exclude` (parteneri/furnizori) sunt EXCLUȘI implicit.

Auth: header `X-API-Key` (SHA-256 verificat în tabelul `api_keys`, doar chei `is_active`)
SAU header `X-CTS-Token` (cheia feed-ului CTS din config) — vezi `_verify_any_key`.
Rate limit: reutilizat din satisfaction_api (60 req/min per cheie), inclusiv pentru cheia CTS.

Performanță: agregarea lunară se face într-un CTE limitat la clienții din pagina curentă
(nu pe tot tabelul), deci costul nu crește cu numărul total de clienți.
Migrație asociată: `migrations/20260803_client_satisfaction_feed_indexes.sql`.
"""

import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.config import get_settings
# Auth + rate limit pe X-API-Key sunt single-source în satisfaction_api: aceeași tabelă
# `api_keys`, aceeași fereastră de rate limit. Nu duplicăm logica de verificare a cheilor.
from app.api.v1.satisfaction_api import _verify_api_key, _rate_limit

logger = logging.getLogger("mailguard.client_satisfaction_feed")
router = APIRouter()


def _verify_any_key(request: Request, db: Session) -> str:
    """Acceptă DOUĂ mecanisme de autentificare, în ordinea de mai jos.

      1) `X-API-Key`  — chei din tabelul `api_keys` (mecanismul propriu al feed-urilor externe).
      2) `X-CTS-Token` — cheia feed-ului CTS din config/.env.

    De ce ambele (decizie Raul Covaci, 2026-08-03): în Setări → Conexiune API e afișată o
    singură cheie, cea CTS, iar consumatorii o încearcă natural și pe acest endpoint. Un
    singur secret de gestionat.

    COMPROMIS ASUMAT: cheia CTS nu mai poate fi revocată independent de accesul la datele
    de satisfacție — rotirea ei rupe simultan feed-ul de emailuri ȘI acest endpoint. Dacă
    e nevoie de revocare separată, emite o cheie dedicată în `api_keys` și scoate ramura
    CTS de mai jos; restul endpointului nu se schimbă.

    Rate limit: cheia CTS intră în aceeași fereastră (60 req/min) ca cele din `api_keys`,
    sub o identitate proprie — altfel ar fi ocolit complet limita.
    """
    cts_token = (request.headers.get("X-CTS-Token") or "").strip()
    if cts_token and not (request.headers.get("X-API-Key") or "").strip():
        import hashlib
        import hmac as _hmac
        expected = (get_settings().cts_feed_api_key or "").strip()
        if not expected:
            raise HTTPException(503, detail="Cheia CTS nu este configurată pe server")
        if not _hmac.compare_digest(cts_token, expected):
            raise HTTPException(401, detail="X-CTS-Token invalid")
        # Identitate distinctă pentru rate limit (hash, ca să nu ținem secretul în memorie).
        rl_id = "cts:" + hashlib.sha256(cts_token.encode()).hexdigest()
        if not _rate_limit(rl_id):
            raise HTTPException(429, detail="Rate limit depășit — max 60 req/min per cheie")
        return "cts-feed-key"

    # Fără X-CTS-Token (sau cu X-API-Key prezent) -> mecanismul standard.
    # Mesajul de eroare menționează ambele variante, ca să nu trimită omul în zid.
    if not (request.headers.get("X-API-Key") or "").strip():
        raise HTTPException(401, detail="Cheie lipsă — trimite header X-API-Key sau X-CTS-Token")
    return _verify_api_key(request, db)

DEFAULT_LIMIT = 100
MAX_LIMIT = 1000

# Scorul implicit pentru clienții fără niciun snapshot lunar calculat.
DEFAULT_SATISFACTION_PCT = 100.0

# Luni în format YYYY-MM.
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")

# Nume de luni în română, pentru cheile din `istoric_satisfactie` când
# `format_luni=nume` (ex. "iulie 2026"). Implicit rămâne YYYY-MM (sortabil, neambiguu).
_MONTH_NAMES_RO = {
    "01": "ianuarie", "02": "februarie", "03": "martie", "04": "aprilie",
    "05": "mai", "06": "iunie", "07": "iulie", "08": "august",
    "09": "septembrie", "10": "octombrie", "11": "noiembrie", "12": "decembrie",
}


def _month_label(month_key: str, fmt: str) -> str:
    """'2026-07' -> '2026-07' (implicit) sau 'iulie 2026' (fmt='nume')."""
    if fmt != "nume":
        return month_key
    year, _, mm = month_key.partition("-")
    return f"{_MONTH_NAMES_RO.get(mm, mm)} {year}"


def _normalize_cui(value: str) -> str:
    """'RO 12345678' / 'ro12345678' -> '12345678'. Doar cifrele contează la potrivire."""
    return re.sub(r"[^0-9]", "", value or "")


@router.get("/ext/clients/satisfaction")
def get_client_satisfaction_feed(
    request: Request,
    q: Optional[str] = Query(
        default=None, max_length=200,
        description="Căutare liberă: nume (parțial), CUI (cu sau fără RO) sau ID. Gol = toți clienții.",
    ),
    client_id: Optional[int] = Query(default=None, description="ID intern Cargo360 — potrivire exactă"),
    iris_client_id: Optional[int] = Query(default=None, description="ID client din IRIS — potrivire exactă"),
    cui: Optional[str] = Query(default=None, max_length=64, description="CUI — potrivire exactă, normalizată (RO ignorat)"),
    from_month: Optional[str] = Query(default=None, description="YYYY-MM — limita inferioară a istoricului (inclusiv)"),
    to_month: Optional[str] = Query(default=None, description="YYYY-MM — limita superioară a istoricului (inclusiv)"),
    doar_cu_scor: bool = Query(default=False, description="true = numai clienții care au cel puțin o lună calculată"),
    include_inactivi: bool = Query(default=False, description="true = include și clienții marcați inactivi"),
    include_exclusi: bool = Query(default=False, description="true = include și partenerii/furnizorii excluși din satisfacție"),
    format_luni: str = Query(default="key", pattern="^(key|nume)$",
                             description="Cheile din istoric: 'key' = 2026-07 (implicit), 'nume' = iulie 2026"),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """Lista de clienți cu gradul de satisfacție (medie generală + istoric lunar).

    Autentificare: header `X-API-Key: <cheie>` SAU `X-CTS-Token: <cheia CTS>` (aceeași
    cheie afișată în Setări → Conexiune API). Rate limit: 60 req/min per cheie.

    Exemple:
      GET /api/v1/ext/clients/satisfaction?limit=50
      GET /api/v1/ext/clients/satisfaction?q=RO12345678
      GET /api/v1/ext/clients/satisfaction?q=transport
      GET /api/v1/ext/clients/satisfaction?cui=12345678
      GET /api/v1/ext/clients/satisfaction?doar_cu_scor=true&limit=500
      GET /api/v1/ext/clients/satisfaction?from_month=2026-01&to_month=2026-07

    Răspuns:
      {
        "ok": true,
        "total": 15720,
        "limit": 100,
        "offset": 0,
        "has_more": true,
        "items": [
          {
            "id_client": 4088,
            "iris_id_client": 91234,
            "client_nume": "Transport Demo SRL",
            "client_cui": "RO12345678",
            "client_satisfactie": 60.7,
            "are_scor_calculat": true,
            "luni_calculate": 2,
            "istoric_satisfactie": { "2026-06": 71.4, "2026-07": 50.0 }
          },
          {
            "id_client": 4091,
            "iris_id_client": null,
            "client_nume": "Client Fara Scor SRL",
            "client_cui": null,
            "client_satisfactie": 100.0,
            "are_scor_calculat": false,
            "luni_calculate": 0,
            "istoric_satisfactie": {}
          }
        ]
      }

    Erori: 401 cheie lipsă/invalidă · 429 rate limit · 400 parametri invalizi.
    """
    _verify_any_key(request, db)

    for value, name in ((from_month, "from_month"), (to_month, "to_month")):
        if value and not _MONTH_RE.match(value):
            raise HTTPException(400, detail=f"{name} trebuie să fie format YYYY-MM")
    if from_month and to_month and from_month > to_month:
        raise HTTPException(400, detail="from_month nu poate fi după to_month")

    # ── Filtrul pe clienți ────────────────────────────────────────────────────
    conditions: list = []
    params: dict = {"limit": limit, "offset": offset}

    if not include_inactivi:
        conditions.append("COALESCE(c.is_active, true) = true")
    if not include_exclusi:
        conditions.append("c.satisfaction_exclude = false")

    if client_id is not None:
        conditions.append("c.id = :client_id")
        params["client_id"] = client_id
    if iris_client_id is not None:
        conditions.append("c.iris_client_id = :iris_client_id")
        params["iris_client_id"] = iris_client_id
    if cui:
        normalized = _normalize_cui(cui)
        if not normalized:
            raise HTTPException(400, detail="cui nu conține nicio cifră")
        conditions.append(
            "upper(regexp_replace(COALESCE(c.cui, ''), '[^0-9]', '', 'g')) = :cui_norm"
        )
        params["cui_norm"] = normalized

    # `q` = căutare liberă. Ordinea de interpretare: numeric -> ID sau CUI; altfel nume.
    if q:
        term = q.strip()
        if term:
            digits = _normalize_cui(term)
            # Un termen numeric poate fi ID intern, ID IRIS sau CUI — încercăm toate,
            # ca aplicația externă să nu fie obligată să știe ce tip de identificator are.
            if digits and re.fullmatch(r"(?i)(ro)?\s*\d+", term.replace(" ", "")):
                clauses = [
                    "upper(regexp_replace(COALESCE(c.cui, ''), '[^0-9]', '', 'g')) = :q_digits"
                ]
                params["q_digits"] = digits
                # Integerul poate depăși bigint pentru un input absurd de lung; gardăm.
                if len(digits) <= 18:
                    clauses.append("c.id = :q_int")
                    clauses.append("c.iris_client_id = :q_int")
                    params["q_int"] = int(digits)
                conditions.append("(" + " OR ".join(clauses) + ")")
            else:
                conditions.append("c.name ILIKE :q_like")
                params["q_like"] = f"%{term}%"

    if doar_cu_scor:
        conditions.append(
            "EXISTS (SELECT 1 FROM client_satisfaction_snapshots s0 "
            "WHERE s0.client_id = c.id AND s0.satisfaction_pct IS NOT NULL)"
        )

    where = " AND ".join(conditions) if conditions else "TRUE"

    # ── Total (pentru paginare) ───────────────────────────────────────────────
    total = db.execute(
        text(f"SELECT COUNT(*) FROM clients c WHERE {where}"), params
    ).scalar() or 0

    # ── Pagina de clienți + agregare istoricului DOAR pentru ei ───────────────
    # `page` limitează la `limit` clienți, apoi agregarea lunară se face pe acest
    # subset. Așa costul nu depinde de cei 15.7k clienți totali.
    month_conditions = ["s.satisfaction_pct IS NOT NULL"]
    if from_month:
        month_conditions.append("s.month_key >= :from_month")
        params["from_month"] = from_month
    if to_month:
        month_conditions.append("s.month_key <= :to_month")
        params["to_month"] = to_month
    month_where = " AND ".join(month_conditions)

    rows = db.execute(text(f"""
        WITH page AS (
            SELECT c.id, c.iris_client_id, c.name, c.cui
            FROM clients c
            WHERE {where}
            ORDER BY c.name ASC, c.id ASC
            LIMIT :limit OFFSET :offset
        ),
        hist AS (
            SELECT s.client_id,
                   AVG(s.satisfaction_pct)::numeric(6,2) AS medie,
                   COUNT(*)                              AS luni,
                   jsonb_object_agg(s.month_key, ROUND(s.satisfaction_pct, 2)
                                    ORDER BY s.month_key) AS istoric
            FROM client_satisfaction_snapshots s
            JOIN page p ON p.id = s.client_id
            WHERE {month_where}
            GROUP BY s.client_id
        )
        SELECT p.id, p.iris_client_id, p.name, p.cui,
               h.medie, h.luni, h.istoric
        FROM page p
        LEFT JOIN hist h ON h.client_id = p.id
        ORDER BY p.name ASC, p.id ASC
    """), params).fetchall()

    items = []
    for row in rows:
        client_pk, iris_id, name, client_cui, medie, luni, istoric = row
        has_score = medie is not None
        istoric_map = dict(istoric or {})
        if format_luni == "nume":
            istoric_map = {_month_label(k, "nume"): v for k, v in istoric_map.items()}
        items.append({
            "id_client": client_pk,
            "iris_id_client": iris_id,
            "client_nume": name,
            "client_cui": client_cui,
            # Fără scor calculat -> 100% (decizie de business, vezi docstring-ul modulului).
            "client_satisfactie": float(medie) if has_score else DEFAULT_SATISFACTION_PCT,
            "are_scor_calculat": has_score,
            "luni_calculate": int(luni or 0),
            "istoric_satisfactie": {k: float(v) for k, v in istoric_map.items()},
        })

    return {
        "ok": True,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": (offset + len(items)) < total,
        "items": items,
    }
