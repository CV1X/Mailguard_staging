"""IRIS audio transcription client — pentru modulul Apeluri.

STARE: contract CONFIRMAT de Razvan (2026-07-01). Endpoint gata pe partea IRIS, fara
inregistrare separata — proxy la Whisper local (whisper-large-v3, GPU intern, cost=0).
  - POST {IRIS_API_URL}/external-ai/transcribe-audio, multipart/form-data (file + language).
  - Auth: ACEEASI cheie ca /external-ai/run-prompt (validata pe tabela apps, id=24 enabled).
  - Sincron (fara polling/job-id); timeout server-side 600s; limita ~50MB/request (nginx).
  - Raspuns Whisper brut: { text, language, ... } — FARA "usage" (Whisper nu intoarce).

Toate erorile sunt întoarse ca dict structurat (niciodată raise) — call_transcribe.py
degradează sigur (transcript_status='error') dacă endpoint-ul nu răspunde cum se așteaptă.
"""
import os
import base64
import logging
import httpx

logger = logging.getLogger("mailguard.iris_transcribe")

DEFAULT_TIMEOUT = 600.0  # confirmat Razvan: Whisper server-side timeout = 600s, sincron (fara polling/job-id)


def _resolve_url() -> str:
    explicit = os.getenv("IRIS_TRANSCRIBE_URL", "").strip()
    if explicit:
        return explicit
    base = os.getenv("IRIS_API_URL", "").strip().rstrip("/")
    return f"{base}/external-ai/transcribe-audio" if base else ""


def _resolve_key() -> str:
    # Confirmat de Razvan (2026-07-01): /external-ai/transcribe-audio valideaza pe
    # ACEEASI cheie ca /external-ai/run-prompt (tabela apps, staging.cargo360 id=24
    # deja enabled) -> acelasi chain ca iris_ai._resolve_key(), NU doar IRIS_API_KEY.
    return (os.getenv("IRIS_TRANSCRIBE_KEY", "").strip()
            or os.getenv("IRIS_AI_KEY", "").strip()
            or os.getenv("IRIS_API_KEY", "").strip()
            or os.getenv("NOVA_LLM_KEY", "").strip()
            or os.getenv("IRIS_LLM_KEY", "").strip())


def is_configured() -> bool:
    return bool(_resolve_url() and _resolve_key())


def transcribe(audio_path: str, *, language: str = "ro", call_id: str = None) -> dict:
    """Trimite un fișier audio la IRIS pentru transcriere. Returnează:
      { ok: bool, transcript: str, language: str|None, usage: dict|None, error: {...}|None }

    Format upload PRESUPUS = multipart/form-data (file + language); de ajustat dacă IRIS
    cere altceva (base64 în JSON, sau URL semnat) — vezi Prompt 2 (Razvan)."""
    url = _resolve_url()
    key = _resolve_key()
    if not url:
        return {"ok": False, "transcript": "", "language": None, "usage": None,
                "error": {"code": "NOT_CONFIGURED", "message": "IRIS_TRANSCRIBE_URL / IRIS_API_URL not set"}}
    if not key:
        return {"ok": False, "transcript": "", "language": None, "usage": None,
                "error": {"code": "NOT_CONFIGURED", "message": "IRIS_TRANSCRIBE_KEY / IRIS_API_KEY not set"}}
    if not audio_path or not os.path.exists(audio_path):
        return {"ok": False, "transcript": "", "language": None, "usage": None,
                "error": {"code": "INVALID_REQUEST", "message": "audio file missing on disk"}}

    headers = {"Authorization": "Bearer " + key}
    try:
        with open(audio_path, "rb") as fh:
            files = {"file": (os.path.basename(audio_path), fh, "audio/mpeg")}
            data = {"language": language, "client": "Cargo360"}
            r = httpx.post(url, headers=headers, files=files, data=data, timeout=DEFAULT_TIMEOUT)
    except Exception as e:
        logger.warning("iris transcribe transport error call_id=%s: %s", call_id, e)
        return {"ok": False, "transcript": "", "language": None, "usage": None,
                "error": {"code": "TRANSPORT", "message": str(e)[:200]}}

    if r.status_code != 200:
        logger.warning("iris transcribe HTTP %s call_id=%s: %s", r.status_code, call_id, r.text[:200])
        return {"ok": False, "transcript": "", "language": None, "usage": None,
                "error": {"code": "HTTP_" + str(r.status_code), "message": r.text[:200]}}

    try:
        payload = r.json()
    except Exception as e:
        return {"ok": False, "transcript": "", "language": None, "usage": None,
                "error": {"code": "BAD_JSON", "message": str(e)[:200]}}

    if isinstance(payload, dict) and payload.get("ok") is False:
        return {"ok": False, "transcript": "", "language": None, "usage": payload.get("usage"),
                "error": payload.get("error")}

    transcript = ""
    if isinstance(payload, dict):
        transcript = payload.get("transcript") or payload.get("text") or ""
    return {"ok": True, "transcript": transcript,
            "language": payload.get("language") if isinstance(payload, dict) else None,
            "usage": payload.get("usage") if isinstance(payload, dict) else None,
            "error": None}
