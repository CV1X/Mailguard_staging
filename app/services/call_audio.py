"""Download audio (mp3) pentru apeluri cu audio_status='pending' -> disc local.

STARE: contract CONFIRMAT de Razvan (2026-07-01), pe baza integrarii call-analytics:
  - recording_ref (capturat la ingest in while1_ingest._insert_call, din recording_url sau
    fallback prima linie din monitor_urls) e fie un URL complet (GET direct, Bearer), fie un
    id de fisier care necesita construirea URL-ului de fallback:
    {WHILE1_API_URL}/tools/play-record?monitor=<file_id>&download=1&fname=<nume>.
  - Validare: raspuns sub 1KB = fara inregistrare reala / auth esuat -> tratat ca eroare
    (NU se scrie fisier corupt pe disc).
  - Retentie audio pe While1 nedocumentata -> descarcam prompt, nu ne bazam pe disponibilitate
    lunga (comportament conservator, mirror call-analytics).

Stocarea locală (CALL_AUDIO_HOST_PREFIX) e mirror pe pattern-ul de attachments (protecție
realpath la traversal).
"""
import os
import re
import time
import logging

import httpx
from sqlalchemy import text
from app.database import SessionLocal
from app.services import while1_ingest

logger = logging.getLogger("mailguard.call_audio")

CALL_AUDIO_HOST_PREFIX = os.getenv("CALL_AUDIO_HOST_PREFIX", "/home/mail-data/call_audio")
DEFAULT_TIMEOUT = 90.0   # confirmat Razvan: call-analytics foloseste timeout 90s la download
MIN_VALID_BYTES = 1024   # sub 1KB = fara inregistrare reala / auth esuat (confirmat Razvan)


def host_path(storage_path: str):
    """Rezolvă un storage_path stocat -> path absolut pe disc, cu protecție la traversal."""
    if not storage_path:
        return None
    real = os.path.realpath(storage_path)
    base = os.path.realpath(CALL_AUDIO_HOST_PREFIX)
    if real != base and not real.startswith(base + os.sep):
        return None
    return real


def _resolve_download_url(c, recording_ref: str) -> str:
    """recording_ref e fie URL complet (recording_url / monitor_urls), fie un id de fisier
    care necesita URL-ul de fallback (play-record). Confirmat de Razvan."""
    if recording_ref.startswith("http"):
        return recording_ref
    return "%s/tools/play-record?monitor=%s&download=1&fname=%s" % (
        c["url"], recording_ref, recording_ref)


def _download_one(c, call_id: str, recording_ref: str) -> str:
    """Descarcă mp3-ul de la While1 pentru un apel. Returnează path-ul absolut pe disc.
    Ridică excepție daca raspunsul e sub MIN_VALID_BYTES (fara inregistrare reala)."""
    headers = {"Authorization": "Bearer " + c["token"]}
    url = _resolve_download_url(c, recording_ref)
    r = httpx.get(url, headers=headers, timeout=DEFAULT_TIMEOUT, follow_redirects=True)
    r.raise_for_status()
    if len(r.content) < MIN_VALID_BYTES:
        raise RuntimeError("raspuns sub %dB — fara inregistrare reala / auth esuat" % MIN_VALID_BYTES)
    fname = re.sub(r"[^A-Za-z0-9_.-]", "_", call_id) + ".mp3"
    day_dir = time.strftime("%Y/%m")
    base_dir = os.path.join(CALL_AUDIO_HOST_PREFIX, day_dir)
    os.makedirs(base_dir, exist_ok=True)
    fpath = os.path.join(base_dir, fname)
    with open(fpath, "wb") as fh:
        fh.write(r.content)
    return fpath


def process_pending_batch(limit: int = 50) -> dict:
    """Descarcă audio pentru apeluri audio_status='pending'. Rulat din /process/run-now."""
    c = while1_ingest._cfg()
    if not while1_ingest.is_configured():
        return {"ok": False, "skipped": "while1_not_configured"}

    db = SessionLocal()
    downloaded, errors, no_recording = 0, 0, 0
    try:
        rows = db.execute(text(
            "SELECT id, call_id, recording_ref FROM calls WHERE audio_status='pending' "
            "ORDER BY started_at DESC LIMIT :lim"), {"lim": limit}).fetchall()
        for row in rows:
            call_pk, call_id, recording_ref = row[0], row[1], row[2]
            if not recording_ref:
                db.execute(text(
                    "UPDATE calls SET audio_status='no_recording', updated_at=now() WHERE id=:id"),
                    {"id": call_pk})
                db.commit()
                no_recording += 1
                continue
            try:
                fpath = _download_one(c, call_id, recording_ref)
                db.execute(text(
                    "UPDATE calls SET audio_path=:p, audio_status='downloaded', updated_at=now() "
                    "WHERE id=:id"), {"p": fpath, "id": call_pk})
                db.commit()
                downloaded += 1
            except Exception as e:
                db.rollback()
                logger.warning("call_audio download fail id=%s: %s", call_pk, str(e)[:200])
                db.execute(text(
                    "UPDATE calls SET audio_status='error', updated_at=now() WHERE id=:id"),
                    {"id": call_pk})
                db.commit()
                errors += 1
    finally:
        db.close()
    return {"ok": True, "downloaded": downloaded, "errors": errors, "no_recording": no_recording}
