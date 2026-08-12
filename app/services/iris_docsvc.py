"""OPS-2026-0122 — Client pentru zona centralizata de documente IRIS.

Cargo360 = sursa de adevar pentru tipuri; IRIS le importa (push) si intoarce id-uri
(iris_template_id) folosite la extractia centralizata.

Endpoints IRIS (base {iris_api_url}/api/v1), toate cu Authorization: Bearer <IRIS_AI_KEY>
(aceeasi cheie ca external-ai/run-prompt):
  GET  /documents/types?app=&category=        -> lista tipuri (pt mapare id)
  POST /documents/types/import  body=[tipuri] -> upsert idempotent pe category+name
  POST /documents/extract                     -> {ok, data, confidence, method, model}

Toate functiile HTTP degradeaza gracios (dict cu ok/status=False/error), nu arunca spre apelant.
"""
import os
import json
import base64
import logging
import threading

import httpx
import psycopg2

from app.config import get_settings
from app.services import iris_ai

logger = logging.getLogger("mailguard.iris_docsvc")
settings = get_settings()

_DOC_SYNC_LOCK = threading.Lock()


def _base_url() -> str:
    return (settings.iris_api_url or "").strip().rstrip("/") + "/api/v1"


def _key() -> str:
    # aceeasi rezolvare ca external-ai/run-prompt (IRIS_AI_KEY -> IRIS_API_KEY -> ...)
    return iris_ai._resolve_key()


def is_configured() -> bool:
    return bool((settings.iris_api_url or "").strip() and _key())


def _headers() -> dict:
    return {"Authorization": "Bearer " + (_key() or "")}


def _conn():
    return psycopg2.connect(
        host=settings.db_host, port=settings.db_port,
        dbname=settings.db_name, user=settings.db_user, password=settings.db_password,
    )


# ── HTTP: tipuri ─────────────────────────────────────────────────────────────
def list_iris_types(app: str = "mailguard") -> list:
    """GET /documents/types?app= — lista tipurilor din IRIS (tolerant la {types:[]} sau [])."""
    with httpx.Client(timeout=60, verify=False) as cl:
        r = cl.get(_base_url() + "/documents/types", params={"app": app}, headers=_headers())
        r.raise_for_status()
        d = r.json()
    if isinstance(d, dict):
        return d.get("types") or d.get("data") or []
    return d if isinstance(d, list) else []


def import_types(types: list) -> dict:
    """POST /documents/types/import — body = array de tipuri; upsert idempotent in IRIS."""
    with httpx.Client(timeout=90, verify=False) as cl:
        r = cl.post(_base_url() + "/documents/types/import", json=types, headers=_headers())
        r.raise_for_status()
        try:
            return r.json()
        except Exception:
            return {"ok": True, "raw": r.text[:200]}


# ── HTTP: extractie centralizata ─────────────────────────────────────────────
def extract_document(iris_template_id, file_bytes: bytes, file_name: str,
                     content_type: str, timeout: float = 90, extra_files=None) -> dict:
    """POST /documents/extract -> {ok, data, confidence, method, model}.
    Nu arunca: la orice problema intoarce {ok:False, error:...}.
    extra_files: pagini suplimentare (base64) pt un segment MULTI-PAGINA fata-verso. Cand sunt
    prezente, trimitem 'pages'=[prima + restul]; 'file_content' ramane pt backward-compat. Endpoint
    IRIS multi-fisier in lucru (outbox #16) — pana atunci apelantul nu trimite extra_files."""
    if not iris_template_id:
        return {"ok": False, "error": "fara iris_template_id (tip nesincronizat in IRIS)"}
    if not is_configured():
        return {"ok": False, "error": "IRIS docsvc neconfigurat (lipsa url/cheie)"}
    first_b64 = base64.b64encode(file_bytes or b"").decode("ascii")
    payload = {
        "document_type_id": int(iris_template_id),
        "file_content": first_b64,
        "file_name": file_name or "document.pdf",
        "content_type": content_type or "application/pdf",
    }
    if extra_files:
        payload["pages"] = [first_b64] + list(extra_files)
    try:
        with httpx.Client(timeout=timeout, verify=False) as cl:
            r = cl.post(_base_url() + "/documents/extract", json=payload, headers=_headers())
        if r.status_code != 200:
            return {"ok": False, "error": "HTTP %s: %s" % (r.status_code, r.text[:200])}
        out = r.json()
        if not isinstance(out, dict):
            return {"ok": False, "error": "raspuns IRIS neasteptat"}
        return out
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


# ── Sync catalog tipuri Cargo360 -> IRIS (push + backfill id) ────────────────
def _write_sync_state(d: dict):
    try:
        with _conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE settings SET value=%s::jsonb, updated_at=NOW() WHERE key='doc_sync.last_result'",
                (json.dumps(d, default=str),))
            conn.commit()
    except Exception:
        logger.exception("doc_sync.last_result write failed")


def _read_active_types() -> list:
    """Tipurile active in forma de export (identic cu GET /documents/types/export)."""
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, category, name, description, extract_fields, extract_prompt, "
            "       detect_prompt, match_titles, extract_via_vision, identify_only, sample_name, sample_mime "
            "FROM document_types WHERE status='active' ORDER BY category, id")
        cols = [c[0] for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return rows


def _export_shape(t: dict) -> dict:
    return {
        "source_id": t.get("id"),
        "source_app": "mailguard",
        "apps": ["mailguard"],
        "category": t.get("category"),
        "name": t.get("name"),
        "description": t.get("description"),
        "extract_fields": t.get("extract_fields"),
        "extract_prompt": t.get("extract_prompt"),
        "detect_prompt": t.get("detect_prompt"),
        "match_titles": t.get("match_titles"),
        "extract_via_vision": t.get("extract_via_vision"),
        "identify_only": t.get("identify_only"),
        "sample_name": t.get("sample_name"),
        "sample_mime": t.get("sample_mime"),
    }


def _match_key(category, name):
    return ((category or "").strip().lower(), (name or "").strip().lower())


def sync_types_to_iris() -> dict:
    """Push toate tipurile active in IRIS (import upsert) + backfill iris_template_id local."""
    if not is_configured():
        return {"status": "error", "message": "IRIS docsvc neconfigurat (lipsa url/cheie)"}
    local = _read_active_types()
    if not local:
        return {"status": "ok", "pushed": 0, "mapped": 0, "message": "niciun tip activ"}
    # 1) push catalog
    try:
        imp = import_types([_export_shape(t) for t in local])
    except Exception as e:
        logger.exception("import_types failed")
        return {"status": "error", "message": "import IRIS esuat: " + str(e)[:200]}
    # 2) citeste id-urile din IRIS si mapeaza pe (category, name)
    mapped = 0
    try:
        iris_types = list_iris_types("mailguard")
        idx = {}
        for it in iris_types:
            tid = it.get("id") or it.get("template_id") or it.get("document_type_id")
            if tid is None:
                continue
            idx[_match_key(it.get("category"), it.get("name"))] = tid
        with _conn() as conn:
            cur = conn.cursor()
            for t in local:
                tid = idx.get(_match_key(t.get("category"), t.get("name")))
                if tid is None:
                    continue
                cur.execute(
                    "UPDATE document_types SET iris_template_id=%s, iris_synced_at=NOW() WHERE id=%s",
                    (int(tid), int(t["id"])))
                mapped += 1
            conn.commit()
    except Exception as e:
        logger.exception("backfill iris ids failed")
        return {"status": "partial", "message": "push ok, mapare id esuata: " + str(e)[:200],
                "pushed": len(local), "mapped": 0}
    return {"status": "ok", "pushed": len(local), "mapped": mapped,
            "iris_count": len(iris_types) if isinstance(iris_types, list) else None,
            "import_resp": imp if isinstance(imp, dict) else None}


def sync_types_guarded() -> dict:
    """Wrapper cu lock anti-suprapunere pt rulare in fundal (daemon thread)."""
    if not _DOC_SYNC_LOCK.acquire(blocking=False):
        return {"status": "running", "message": "Sync tipuri deja in curs"}
    _write_sync_state({"status": "running"})
    try:
        res = sync_types_to_iris()
        _write_sync_state(res)
        return res
    except Exception as e:
        logger.exception("sync_types failed")
        st = {"status": "error", "message": str(e)[:200]}
        _write_sync_state(st)
        return st
    finally:
        _DOC_SYNC_LOCK.release()


def bg_sync_types():
    """Porneste sync-ul in fundal (best-effort, non-blocant). Lock-ul previne suprapunerea."""
    try:
        threading.Thread(target=sync_types_guarded, daemon=True).start()
    except Exception:
        logger.exception("bg_sync_types start failed")
