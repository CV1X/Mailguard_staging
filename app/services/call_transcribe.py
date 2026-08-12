"""Trimite apelurile descărcate (audio_status='downloaded') la IRIS pentru transcriere."""
import logging
from sqlalchemy import text
from app.database import SessionLocal
from app.services import iris_transcribe
from app.services import call_audio

logger = logging.getLogger("mailguard.call_transcribe")


def process_pending_batch(limit: int = 50) -> dict:
    if not iris_transcribe.is_configured():
        return {"ok": False, "skipped": "iris_transcribe_not_configured"}

    db = SessionLocal()
    done, errors = 0, 0
    try:
        rows = db.execute(text(
            "SELECT id, call_id, audio_path FROM calls "
            "WHERE audio_status='downloaded' AND transcript_status='pending' "
            "ORDER BY started_at DESC LIMIT :lim"), {"lim": limit}).fetchall()
        for row in rows:
            call_pk, call_id, audio_path = row[0], row[1], row[2]
            hp = call_audio.host_path(audio_path) or audio_path
            res = iris_transcribe.transcribe(hp, call_id=call_id)
            if res.get("ok"):
                db.execute(text(
                    "UPDATE calls SET transcript=:t, transcript_status='success', updated_at=now() "
                    "WHERE id=:id"), {"t": res.get("transcript") or "", "id": call_pk})
                db.commit()
                done += 1
            else:
                db.execute(text(
                    "UPDATE calls SET transcript_status='error', updated_at=now() WHERE id=:id"),
                    {"id": call_pk})
                db.commit()
                errors += 1
                logger.warning("transcribe fail call_id=%s: %s", call_id, res.get("error"))
    finally:
        db.close()
    return {"ok": True, "transcribed": done, "errors": errors}
