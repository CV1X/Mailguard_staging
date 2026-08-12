"""API endpoints auto-reply no-reply.

Admin endpoints (JWT required):
  GET/PUT  /api/v1/noreply/config         — config SMTP
  POST     /api/v1/noreply/config/test    — test SMTP
  GET/POST /api/v1/noreply/toggle         — switch ON/OFF
  GET/PUT  /api/v1/noreply/template       — șablon email
  GET/POST/DELETE /api/v1/noreply/blacklist — gestionare blacklist

Public (fără auth):
  GET /noreply/unsubscribe?token=<uuid>   — dezabonare one-click
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_admin
from app.database import get_db
from app.services import noreply_sender

router = APIRouter()


# ── Public — dezabonare one-click ────────────────────────────────────────────

@router.get("/noreply/unsubscribe", response_class=HTMLResponse, include_in_schema=False)
def unsubscribe(token: str = Query(...), db: Session = Depends(get_db)):
    email = noreply_sender.use_unsubscribe_token(db, token)
    if not email:
        return HTMLResponse(
            "<html><body style='font-family:Arial;padding:40px;'>"
            "<h2>Link invalid sau deja folosit.</h2>"
            "<p>Dacă doriți dezabonarea, contactați-ne la support@cargotrack.ro.</p>"
            "</body></html>",
            status_code=400
        )
    noreply_sender.add_to_blacklist(db, email, reason="unsubscribe")
    return HTMLResponse(
        "<html><body style='font-family:Arial;padding:40px;max-width:520px;margin:auto;'>"
        "<h2 style='color:#1a7f37;'>Ați fost dezabonat cu succes.</h2>"
        "<p>Adresa <strong>" + email + "</strong> nu va mai primi mesaje automate de la CargoTrack.</p>"
        "<p style='color:#666;font-size:13px;'>Dacă v-ați dezabonat din greșeală, "
        "contactați-ne la support@cargotrack.ro.</p>"
        "</body></html>"
    )


# ── Config SMTP ───────────────────────────────────────────────────────────────

@router.get("/api/v1/noreply/config")
def get_config(db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    cfg = noreply_sender.get_noreply_config(db)
    if not cfg:
        return {"configured": False}
    return {
        "configured": True,
        "smtp_host": cfg["smtp_host"],
        "smtp_port": cfg["smtp_port"],
        "smtp_user": cfg["smtp_user"],
        "from_address": cfg["from_address"],
        "use_tls": cfg["use_tls"],
        "updated_at": cfg.get("updated_at"),
    }


@router.put("/api/v1/noreply/config")
def save_config(body: dict, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    required = ["smtp_host", "smtp_port", "smtp_user", "from_address"]
    for f in required:
        if not body.get(f):
            raise HTTPException(400, f"Câmp obligatoriu lipsă: {f}")
    try:
        noreply_sender.save_noreply_config(
            db,
            smtp_host=body["smtp_host"],
            smtp_port=int(body["smtp_port"]),
            smtp_user=body["smtp_user"],
            from_address=body["from_address"],
            use_tls=bool(body.get("use_tls", True)),
            smtp_password=body.get("smtp_password") or None,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@router.post("/api/v1/noreply/config/test")
def test_config(request: Request, body: dict, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    to_address = (body.get("to_address") or getattr(admin, "email", None) or "").strip()
    if not to_address or "@" not in to_address:
        raise HTTPException(400, "to_address lipsă sau invalid")
    base_url = str(request.base_url).rstrip("/")
    result = noreply_sender.test_noreply_smtp(db, to_address, base_url=base_url)
    if not result["ok"]:
        raise HTTPException(502, result.get("error", "Eroare SMTP"))
    return {"ok": True, "message": f"Email de test trimis la {to_address}"}


# ── Switch ON/OFF ─────────────────────────────────────────────────────────────

@router.get("/api/v1/noreply/toggle")
def get_toggle(db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    enabled = noreply_sender.is_noreply_enabled(db)
    return {"enabled": enabled}


@router.post("/api/v1/noreply/toggle")
def toggle(body: dict, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    enabled = bool(body.get("enabled", False))
    noreply_sender.set_noreply_enabled(db, enabled)
    return {"ok": True, "enabled": enabled,
            "message": "Auto-reply no-reply activat." if enabled else "Auto-reply no-reply oprit."}


# ── Șablon email ──────────────────────────────────────────────────────────────

@router.get("/api/v1/noreply/template")
def get_template(db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    return {"template": noreply_sender.get_template(db),
            "default": noreply_sender.DEFAULT_TEMPLATE}


@router.put("/api/v1/noreply/template")
def save_template(body: dict, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    template = (body.get("template") or "").strip()
    if not template:
        raise HTTPException(400, "template gol")
    if "{unsubscribe_url}" not in template:
        raise HTTPException(400, "Șablonul trebuie să conțină {unsubscribe_url}")
    noreply_sender.save_template(db, template)
    return {"ok": True}


# ── Blacklist ─────────────────────────────────────────────────────────────────

@router.get("/api/v1/noreply/blacklist")
def list_blacklist(db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    items = noreply_sender.get_blacklist(db)
    return {"items": items, "total": len(items)}


@router.post("/api/v1/noreply/blacklist")
def add_blacklist(body: dict, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    email = (body.get("email") or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(400, "email invalid")
    actor = getattr(admin, "username", None) or getattr(admin, "email", None) or "admin"
    noreply_sender.add_to_blacklist(db, email, reason="manual", added_by=actor)
    return {"ok": True}


@router.delete("/api/v1/noreply/blacklist/{email}")
def remove_blacklist(email: str, db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    removed = noreply_sender.remove_from_blacklist(db, email)
    if not removed:
        raise HTTPException(404, "Adresa nu e în blacklist")
    return {"ok": True}
