"""Trimitere auto-reply no-reply la emailuri noi trimise în CTS.

Declanșat din cts.py după ce sent_to_cts_at e setat. Best-effort: nu blochează feed-ul CTS.

Eligibilitate (în ordine):
  1. Switch global ON  (settings key 'autoreply.noreply_enabled')
  2. Config SMTP configurat (noreply_smtp_config)
  3. Adresa destinatarului nu e în noreply_blacklist
  4. Adresa nu e de tip no-reply/automat (regex _AUTOGEN_FROM)
  5. Throttle: max 1 mail la 10 min per adresă (autoreply_send_log, outcome would_send/sent)
  6. autoreply_sent_at deja setat pe email → skip (idempotent)

Șablon: stocat în settings key 'autoreply.noreply_template' (editabil din UI).
Token unsubscribe: UUID generat per email în noreply_unsubscribe_tokens.
"""

import logging
import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.credential_crypto import encrypt_credentials, decrypt_credentials

logger = logging.getLogger("mailguard.noreply_sender")

_NOREPLY_BASE_URL = os.environ.get("NOREPLY_BASE_URL", "").rstrip("/")


def _resolve_base_url(base_url: str) -> str:
    return _NOREPLY_BASE_URL or base_url.rstrip("/")

SETTINGS_KEY_ENABLED  = "autoreply.noreply_enabled"
SETTINGS_KEY_TEMPLATE = "autoreply.noreply_template"
DEFAULT_THROTTLE_MIN  = 10

DEFAULT_TEMPLATE = """\
<p>Bună ziua,</p>

<p>Acesta este un mesaj automat prin care confirmăm că am primit emailul dumneavoastră.<br>
Vă informăm că va fi analizat în cel mai scurt timp posibil.</p>

<p><em>Acesta este un email automat. Vă rugăm să <strong>nu răspundeți</strong> la acest mesaj.</em><br>
Dacă nu doriți să mai primiți emailuri automate de la această adresă, puteți accesa:<br>
<a href="{unsubscribe_url}">Dezabonare</a></p>

<p>Cu stimă,<br>
<strong>Echipa CargoTrack</strong></p>"""

# Regex adrese automate/no-reply — refolosit din spam_detector._AUTOGEN_FROM
_AUTOGEN_FROM = re.compile(
    r'^(noreply|no-reply|donotreply|do-not-reply|auto-reply|autoreply|'
    r'notifications?|alerting|no\.reply|mailer-daemon|postmaster|mail-daemon|bounce)@',
    re.IGNORECASE)

_SENT_OUTCOMES = ["would_send", "sent"]


# ── Config SMTP ──────────────────────────────────────────────────────────────

def get_noreply_config(db: Session) -> Optional[dict]:
    row = db.execute(text(
        "SELECT id, smtp_host, smtp_port, smtp_user, smtp_pass_enc, from_address, use_tls "
        "FROM noreply_smtp_config ORDER BY id LIMIT 1"
    )).fetchone()
    return dict(row._mapping) if row else None


def save_noreply_config(db: Session, smtp_host: str, smtp_port: int, smtp_user: str,
                        from_address: str, use_tls: bool,
                        smtp_password: Optional[str] = None) -> dict:
    existing = get_noreply_config(db)
    if smtp_password:
        pass_enc = encrypt_credentials({"password": smtp_password})
    elif existing:
        pass_enc = existing["smtp_pass_enc"]
    else:
        raise ValueError("Parola SMTP e obligatorie la prima configurare")

    if existing:
        db.execute(text(
            "UPDATE noreply_smtp_config SET smtp_host=:host, smtp_port=:port, smtp_user=:user, "
            "smtp_pass_enc=:pass_enc, from_address=:from_addr, use_tls=:use_tls, updated_at=now() "
            "WHERE id=:id"
        ), {"host": smtp_host, "port": smtp_port, "user": smtp_user, "pass_enc": pass_enc,
            "from_addr": from_address, "use_tls": use_tls, "id": existing["id"]})
    else:
        db.execute(text(
            "INSERT INTO noreply_smtp_config(smtp_host, smtp_port, smtp_user, smtp_pass_enc, "
            "from_address, use_tls) VALUES (:host, :port, :user, :pass_enc, :from_addr, :use_tls)"
        ), {"host": smtp_host, "port": smtp_port, "user": smtp_user, "pass_enc": pass_enc,
            "from_addr": from_address, "use_tls": use_tls})
    db.commit()
    return get_noreply_config(db)


def test_noreply_smtp(db: Session, to_address: str, base_url: str = "") -> dict:
    cfg = get_noreply_config(db)
    if not cfg:
        return {"ok": False, "error": "Config SMTP no-reply nesetat"}
    if is_blacklisted(db, to_address):
        return {"ok": False, "error": f"Adresa {to_address} este în blacklist — dezabonată. Elimină-o din blacklist pentru a trimite test."}
    try:
        password = decrypt_credentials(cfg["smtp_pass_enc"]).get("password", "")
        token = generate_unsubscribe_token(db, to_address)
        resolved = _resolve_base_url(base_url)
        unsub_url = f"{resolved}/noreply/unsubscribe?token={token}"
        template = get_template(db)
        body_text = template.replace("{unsubscribe_url}", unsub_url)
        subject = "[TEST] Confirmare primire email — Cargo360 auto-reply"
        msg = _build_email(cfg, to_address, subject, body_text)
        with smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"], timeout=15) as server:
            if cfg["use_tls"]:
                server.starttls()
            server.login(cfg["smtp_user"], password)
            server.sendmail(cfg["from_address"], [to_address], msg.as_string())
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Switch ON/OFF ─────────────────────────────────────────────────────────────

def is_noreply_enabled(db: Session) -> bool:
    row = db.execute(text(
        "SELECT value FROM settings WHERE key=:k"), {"k": SETTINGS_KEY_ENABLED}
    ).fetchone()
    if not row:
        return False
    try:
        val = row._mapping["value"]
        if isinstance(val, bool):
            return val
        import json
        return bool(json.loads(val) if isinstance(val, str) else val)
    except Exception:
        return False


def set_noreply_enabled(db: Session, enabled: bool) -> None:
    import json
    db.execute(text(
        "INSERT INTO settings(key, value) VALUES (:k, CAST(:v AS jsonb)) "
        "ON CONFLICT (key) DO UPDATE SET value=CAST(:v AS jsonb), updated_at=now()"
    ), {"k": SETTINGS_KEY_ENABLED, "v": json.dumps(enabled)})
    db.commit()


# ── Template ──────────────────────────────────────────────────────────────────

def get_template(db: Session) -> str:
    row = db.execute(text(
        "SELECT value FROM settings WHERE key=:k"), {"k": SETTINGS_KEY_TEMPLATE}
    ).fetchone()
    if not row:
        return DEFAULT_TEMPLATE
    try:
        val = row._mapping["value"]
        import json
        s = json.loads(val) if isinstance(val, str) else val
        return str(s) if s else DEFAULT_TEMPLATE
    except Exception:
        return DEFAULT_TEMPLATE


def save_template(db: Session, template: str) -> None:
    import json
    db.execute(text(
        "INSERT INTO settings(key, value) VALUES (:k, CAST(:v AS jsonb)) "
        "ON CONFLICT (key) DO UPDATE SET value=CAST(:v AS jsonb), updated_at=now()"
    ), {"k": SETTINGS_KEY_TEMPLATE, "v": json.dumps(template)})
    db.commit()


# ── Blacklist ─────────────────────────────────────────────────────────────────

def is_blacklisted(db: Session, email: str) -> bool:
    row = db.execute(text(
        "SELECT 1 FROM noreply_blacklist WHERE lower(email)=lower(:e) LIMIT 1"
    ), {"e": email}).fetchone()
    return row is not None


def add_to_blacklist(db: Session, email: str, reason: str = "unsubscribe",
                     added_by: Optional[str] = None) -> None:
    db.execute(text(
        "INSERT INTO noreply_blacklist(email, reason, added_by) VALUES (:e, :r, :by) "
        "ON CONFLICT (lower(email)) DO NOTHING"
    ), {"e": email.lower(), "r": reason, "by": added_by})
    db.commit()


def remove_from_blacklist(db: Session, email: str) -> bool:
    result = db.execute(text(
        "DELETE FROM noreply_blacklist WHERE lower(email)=lower(:e)"
    ), {"e": email})
    db.commit()
    return result.rowcount > 0


def get_blacklist(db: Session) -> list:
    rows = db.execute(text(
        "SELECT email, added_at, added_by, reason FROM noreply_blacklist ORDER BY added_at DESC"
    )).fetchall()
    return [dict(r._mapping) for r in rows]


# ── Token unsubscribe ─────────────────────────────────────────────────────────

def generate_unsubscribe_token(db: Session, email: str) -> str:
    row = db.execute(text(
        "INSERT INTO noreply_unsubscribe_tokens(email) VALUES (:e) RETURNING token"
    ), {"e": email.lower()}).fetchone()
    db.commit()
    return str(row._mapping["token"])


def use_unsubscribe_token(db: Session, token: str) -> Optional[str]:
    """Validează token, marchează used_at, returnează adresa sau None dacă invalid/folosit."""
    row = db.execute(text(
        "SELECT email, used_at FROM noreply_unsubscribe_tokens WHERE token=:t"
    ), {"t": token}).fetchone()
    if not row:
        return None
    m = row._mapping
    if m.get("used_at"):
        return None  # deja folosit
    db.execute(text(
        "UPDATE noreply_unsubscribe_tokens SET used_at=now() WHERE token=:t"
    ), {"t": token})
    db.commit()
    return m["email"]


# ── Throttle (refolosește autoreply_send_log) ─────────────────────────────────

def _recently_sent(db: Session, recipient: str, minutes: int = DEFAULT_THROTTLE_MIN) -> bool:
    row = db.execute(text(
        "SELECT 1 FROM autoreply_send_log "
        "WHERE recipient=:r AND outcome = ANY(:outcomes) "
        "AND created_at > now() - (:m || ' minutes')::interval LIMIT 1"
    ), {"r": recipient.lower(), "outcomes": _SENT_OUTCOMES, "m": str(minutes)}).fetchone()
    return row is not None


def _log_decision(db: Session, email_id: int, recipient: str, outcome: str,
                  reason: str, trigger: str = "noreply_cts") -> None:
    db.execute(text(
        "INSERT INTO autoreply_send_log(email_id, recipient, trigger, outcome, reason, send_mode) "
        "VALUES (:eid, :r, :tr, :out, :reason, 'smtp')"
    ), {"eid": email_id, "r": recipient.lower(), "tr": trigger, "out": outcome, "reason": reason})
    db.commit()


# ── Trimitere efectivă ────────────────────────────────────────────────────────

def _strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html).strip()


def _build_email(cfg: dict, to_address: str, subject: str, body: str) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = cfg["from_address"]
    msg["To"] = to_address
    msg["X-Auto-Response-Suppress"] = "OOF, AutoReply"
    msg["Auto-Submitted"] = "auto-replied"
    is_html = body.lstrip().startswith("<")
    if is_html:
        plain = _strip_tags(body)
        html_body = f"<html><body style='font-family:Arial,sans-serif;font-size:14px;line-height:1.6;'>{body}</body></html>"
    else:
        plain = body
        html_body = f"<html><body style='font-family:Arial,sans-serif;font-size:14px;line-height:1.6;'>{body.replace(chr(10), '<br>')}</body></html>"
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    return msg


def _send_smtp(cfg: dict, to_address: str, msg: MIMEMultipart) -> None:
    password = decrypt_credentials(cfg["smtp_pass_enc"]).get("password", "")
    with smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"], timeout=20) as server:
        if cfg["use_tls"]:
            server.starttls()
        server.login(cfg["smtp_user"], password)
        server.sendmail(cfg["from_address"], [to_address], msg.as_string())


# ── Punct de intrare principal ────────────────────────────────────────────────

def maybe_send_autoreply(db: Session, email_id: int, base_url: str = "") -> None:
    """Verifică eligibilitatea și trimite auto-reply dacă toate condițiile sunt îndeplinite.

    Best-effort: orice excepție e loghată, nu propagată.
    """
    try:
        _do_send(db, email_id, base_url)
    except Exception:
        logger.exception("noreply maybe_send_autoreply failed email_id=%s", email_id)


def _do_send(db: Session, email_id: int, base_url: str) -> None:
    # 1. Switch ON?
    if not is_noreply_enabled(db):
        logger.debug("noreply disabled — skip email_id=%s", email_id)
        return

    # 2. Config SMTP?
    cfg = get_noreply_config(db)
    if not cfg:
        logger.warning("noreply_smtp_config missing — skip email_id=%s", email_id)
        return

    # 3. Citim datele emailului
    row = db.execute(text(
        "SELECT from_address, subject, autoreply_sent_at FROM emails WHERE id=:id"
    ), {"id": email_id}).fetchone()
    if not row:
        return
    m = row._mapping
    to_address = (m.get("from_address") or "").strip()
    if not to_address or "@" not in to_address:
        return

    # 4. Idempotent
    if m.get("autoreply_sent_at"):
        logger.debug("noreply already sent email_id=%s", email_id)
        return

    # 5. Filtru no-reply/automat
    if _AUTOGEN_FROM.match(to_address):
        logger.debug("noreply skip autogen address=%s email_id=%s", to_address, email_id)
        _log_decision(db, email_id, to_address, "skipped_autogen",
                      "adresa expeditor e de tip automat/no-reply")
        return

    # 5b. Filtru domenii interne — nu trimitem auto-reply la adrese @cargotrack.ro / @trakosoft.ro
    _to_lower = to_address.lower()
    if _to_lower.endswith("@cargotrack.ro") or _to_lower.endswith("@trakosoft.ro"):
        logger.debug("noreply skip internal domain address=%s email_id=%s", to_address, email_id)
        _log_decision(db, email_id, to_address, "skipped_internal_domain",
                      "domeniu intern (@cargotrack.ro / @trakosoft.ro) — auto-reply dezactivat")
        return

    # 6. Blacklist
    if is_blacklisted(db, to_address):
        logger.debug("noreply blacklisted address=%s email_id=%s", to_address, email_id)
        _log_decision(db, email_id, to_address, "skipped_blacklist", "adresa e în blacklist")
        return

    # 7. Throttle
    if _recently_sent(db, to_address):
        logger.debug("noreply throttled address=%s email_id=%s", to_address, email_id)
        _log_decision(db, email_id, to_address, "throttled",
                      f"max 1 mail/{DEFAULT_THROTTLE_MIN} min per adresă")
        return

    # 8. Generăm token unsubscribe și construim emailul
    try:
        token = generate_unsubscribe_token(db, to_address)
        resolved = _resolve_base_url(base_url)
        unsub_url = f"{resolved}/noreply/unsubscribe?token={token}"
    except Exception:
        logger.exception("noreply token generation failed email_id=%s", email_id)
        return

    template = get_template(db)
    body_text = template.replace("{unsubscribe_url}", unsub_url)
    original_subject = (m.get("subject") or "").strip()
    subject = f"Re: {original_subject}" if original_subject else "Confirmare primire email"

    try:
        msg = _build_email(cfg, to_address, subject, body_text)
        _send_smtp(cfg, to_address, msg)
    except Exception as e:
        logger.error("noreply SMTP send failed email_id=%s to=%s: %s", email_id, to_address, e)
        _log_decision(db, email_id, to_address, "send_error", str(e))
        return

    # 9. Marcăm email-ul și loghăm succes
    db.execute(text(
        "UPDATE emails SET autoreply_sent_at=now() WHERE id=:id"
    ), {"id": email_id})
    _log_decision(db, email_id, to_address, "sent", "auto-reply trimis cu succes")
    logger.info("noreply sent email_id=%s to=%s", email_id, to_address)
