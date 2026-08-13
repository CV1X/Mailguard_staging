"""v2.8.0 — Export baza de date pentru dezvoltare locala.

POST /api/v1/db-export/start        -> porneste pg_dump in fundal, intoarce job_id
GET  /api/v1/db-export/status       -> starea exportului curent
GET  /api/v1/db-export/download/{f} -> descarca arhiva
GET  /api/v1/db-export/list         -> exporturile disponibile

DOAR pentru rolul `developer` (vezi require_role mai jos). Nu e o functie de
comoditate: dump-ul contine emailuri reale, clienti, angajati si inregistrari
de apeluri. Fiecare pornire si fiecare descarcare se scriu in audit_log.

De ce asincron: dump-ul e ~195 MB si dureaza ~30s. Intr-un request sincron ar
depasi timeout-ul gunicorn (60s) pe o baza mai mare si ar bloca un worker.
"""
import os
import re
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import get_db
from app.services import access_control as _ac

router = APIRouter()

APP_DIR = Path("/opt/iris-mailguard")
EXPORT_DIR = APP_DIR / "storage" / "db-exports"
DB_CONTAINER = os.getenv("MAILGUARD_DB_CONTAINER", "mailguard-db")
RETENTION = 3          # cite arhive pastram (fiecare ~195 MB)
FILENAME_RE = re.compile(r"^mailguard_db_[0-9]{8}_[0-9]{6}\.dump$")

# Doar developer. Consecvent cu zona Setari, unde sta butonul.
require_developer = _ac.require_role(_ac.ROLE_DEVELOPER)

# Starea exportului curent. Un singur export odata (pg_dump incarca DB-ul).
_state = {"running": False, "filename": None, "started_at": None,
          "finished_at": None, "error": None, "actor": None}
_lock = threading.Lock()


def _envval(key: str) -> str:
    """Citeste o valoare din .env (aceeasi sursa ca scripts/migrate.sh)."""
    try:
        with open(APP_DIR / ".env", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith(f"{key}="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def _audit(db: Session, actor: str, action: str, details: dict,
           request: Optional[Request] = None) -> None:
    """Scrie in audit_log. Nu arunca — auditul nu trebuie sa rupa operatiunea,
    dar absenta lui se vede in loguri."""
    ip = None
    ua = None
    if request is not None:
        ip = request.client.host if request.client else None
        ua = request.headers.get("user-agent")
    try:
        db.execute(text("""
            INSERT INTO audit_log (actor, action, entity_type, details, ip_address, user_agent)
            VALUES (:actor, :action, 'db_export', CAST(:details AS jsonb), CAST(:ip AS inet), :ua)
        """), {"actor": actor, "action": action, "details": __import__("json").dumps(details),
               "ip": ip, "ua": ua})
        db.commit()
    except Exception:
        db.rollback()


def _prune() -> None:
    """Pastreaza ultimele RETENTION arhive."""
    try:
        files = sorted(EXPORT_DIR.glob("mailguard_db_*.dump"),
                       key=lambda f: f.stat().st_mtime, reverse=True)
        for f in files[RETENTION:]:
            f.unlink(missing_ok=True)
    except Exception:
        pass


def _run_dump(target: Path, db_user: str, db_name: str, actor: str) -> None:
    """pg_dump -Fc din containerul Postgres, in fundal.

    Scrie intii in .part si redenumeste la final: o descarcare concurenta nu
    poate prinde un fisier incomplet.
    """
    part = target.with_suffix(".part")
    try:
        with open(part, "wb") as out:
            proc = subprocess.run(
                ["docker", "exec", DB_CONTAINER,
                 "pg_dump", "-U", db_user, "-d", db_name, "-Fc"],
                stdout=out, stderr=subprocess.PIPE, timeout=1800,
            )
        if proc.returncode != 0:
            part.unlink(missing_ok=True)
            err = (proc.stderr or b"").decode("utf-8", "replace")[-500:]
            with _lock:
                _state.update(running=False, error=f"pg_dump a esuat: {err}",
                              finished_at=datetime.now(timezone.utc).isoformat())
            return
        if part.stat().st_size == 0:
            part.unlink(missing_ok=True)
            with _lock:
                _state.update(running=False, error="dump gol",
                              finished_at=datetime.now(timezone.utc).isoformat())
            return
        part.rename(target)
        _prune()
        with _lock:
            _state.update(running=False, filename=target.name, error=None,
                          finished_at=datetime.now(timezone.utc).isoformat())
    except subprocess.TimeoutExpired:
        part.unlink(missing_ok=True)
        with _lock:
            _state.update(running=False, error="timeout (30 min)",
                          finished_at=datetime.now(timezone.utc).isoformat())
    except Exception as e:
        part.unlink(missing_ok=True)
        with _lock:
            _state.update(running=False, error=str(e)[:300],
                          finished_at=datetime.now(timezone.utc).isoformat())


@router.post("/db-export/start")
def start_export(request: Request, db: Session = Depends(get_db),
                 user=Depends(require_developer)):
    """Porneste un export nou. Un singur export odata."""
    with _lock:
        if _state["running"]:
            raise HTTPException(409, "Un export e deja in curs. Asteapta-l sa se termine.")
        _state.update(running=True, filename=None, error=None,
                      started_at=datetime.now(timezone.utc).isoformat(),
                      finished_at=None,
                      actor=user.get("username") or user.get("email"))

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    db_user = _envval("DB_USER") or "mailguard"
    db_name = _envval("DB_NAME") or "mailguard"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    target = EXPORT_DIR / f"mailguard_db_{stamp}.dump"

    actor = user.get("username") or user.get("email") or "?"
    _audit(db, actor, "db_export_start", {"filename": target.name, "db": db_name}, request)

    threading.Thread(target=_run_dump, args=(target, db_user, db_name, actor),
                     daemon=True).start()
    return {"ok": True, "filename": target.name,
            "message": "Export pornit. Dureaza ~30 secunde pentru ~195 MB."}


@router.get("/db-export/status")
def export_status(user=Depends(require_developer)):
    """Starea exportului curent."""
    with _lock:
        st = dict(_state)
    if st["filename"]:
        f = EXPORT_DIR / st["filename"]
        st["size_bytes"] = f.stat().st_size if f.is_file() else None
        st["ready"] = f.is_file()
    else:
        st["size_bytes"] = None
        st["ready"] = False
    return st


@router.get("/db-export/list")
def list_exports(user=Depends(require_developer)):
    """Exporturile disponibile pentru descarcare."""
    items = []
    if EXPORT_DIR.is_dir():
        for f in sorted(EXPORT_DIR.glob("mailguard_db_*.dump"),
                        key=lambda x: x.stat().st_mtime, reverse=True):
            stt = f.stat()
            items.append({
                "filename": f.name,
                "size_bytes": stt.st_size,
                "created_at": datetime.fromtimestamp(stt.st_mtime, tz=timezone.utc).isoformat(),
            })
    return {"count": len(items), "retention": RETENTION, "exports": items}


@router.get("/db-export/download/{filename}")
def download_export(filename: str, request: Request, db: Session = Depends(get_db),
                    user=Depends(require_developer)):
    """Descarca o arhiva. Fiecare descarcare se auditeaza separat de pornire —
    un export poate fi descarcat de mai multe ori, si vrem sa stim de cite."""
    if not FILENAME_RE.match(filename):
        raise HTTPException(400, "Nume de fisier invalid")
    path = EXPORT_DIR / filename
    if not path.is_file():
        raise HTTPException(404, "Export inexistent sau expirat")

    actor = user.get("username") or user.get("email") or "?"
    _audit(db, actor, "db_export_download",
           {"filename": filename, "size_bytes": path.stat().st_size}, request)

    return FileResponse(path, media_type="application/octet-stream",
                        filename=filename)
