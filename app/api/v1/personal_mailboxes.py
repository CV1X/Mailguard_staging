"""Personal mailbox management API (T1).

All endpoints scoped to the authenticated user (user_id from JWT).
No cross-user data leaks: every query filters AND user_id = :uid.
"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel, Field

from app.database import get_db
from app.api.v1.auth import get_current_admin
from app.services.credential_crypto import encrypt_credentials, decrypt_credentials
from app.services import personal_imap

logger = logging.getLogger("mailguard.personal_mailboxes")
router = APIRouter()


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class MailboxCreate(BaseModel):
    label: str = Field(..., min_length=1, max_length=120)
    imap_host: str = Field(..., min_length=1, max_length=255)
    imap_port: int = Field(993, ge=1, le=65535)
    imap_ssl: bool = True
    email_address: str = Field(..., min_length=5, max_length=320)
    password: str = Field(..., min_length=1, max_length=500)


class MailboxUpdate(BaseModel):
    label: Optional[str] = Field(None, min_length=1, max_length=120)
    imap_host: Optional[str] = Field(None, min_length=1, max_length=255)
    imap_port: Optional[int] = Field(None, ge=1, le=65535)
    imap_ssl: Optional[bool] = None
    email_address: Optional[str] = Field(None, min_length=5, max_length=320)
    password: Optional[str] = Field(None, min_length=1, max_length=500)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_account_or_404(db: Session, account_id: int, user_id: int) -> dict:
    row = db.execute(text("""
        SELECT id, user_id, label, imap_host, imap_port, imap_ssl,
               email_address, cred_enc, status, last_error, last_poll_at, last_uid,
               created_at, updated_at
        FROM personal_mailbox_accounts
        WHERE id = :id AND user_id = :uid
    """), {"id": account_id, "uid": user_id}).fetchone()
    if not row:
        raise HTTPException(404, "Account not found")
    return dict(row._mapping)


def _row_to_public(row: dict) -> dict:
    """Strip cred_enc from API response."""
    return {k: v for k, v in row.items() if k != "cred_enc"}


def _validate_and_test(host: str, port: int, ssl: bool, email: str, password: str) -> tuple[str, Optional[str]]:
    """Run IMAP test_login. Returns (status, last_error)."""
    ok, err = personal_imap.test_login({
        "imap_host": host,
        "imap_port": port,
        "imap_ssl": ssl,
        "email_address": email,
        "_password": password,
    })
    return ("active" if ok else "error"), err


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/personal-mailboxes")
def list_mailboxes(db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    rows = db.execute(text("""
        SELECT id, user_id, label, imap_host, imap_port, imap_ssl,
               email_address, status, last_error, last_poll_at, last_uid,
               created_at, updated_at
        FROM personal_mailbox_accounts
        WHERE user_id = :uid
        ORDER BY created_at DESC
    """), {"uid": int(admin["id"])}).fetchall()
    return [dict(r._mapping) for r in rows]


@router.post("/personal-mailboxes", status_code=201)
def create_mailbox(body: MailboxCreate, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    uid = int(admin["id"])

    # Check duplicate
    dup = db.execute(text("""
        SELECT id FROM personal_mailbox_accounts
        WHERE user_id = :uid AND email_address = :email
    """), {"uid": uid, "email": body.email_address.lower()}).fetchone()
    if dup:
        raise HTTPException(409, f"Mailbox '{body.email_address}' already configured for this user")

    cred_enc = encrypt_credentials({"user": body.email_address, "pass": body.password})
    status, last_error = _validate_and_test(body.imap_host, body.imap_port, body.imap_ssl,
                                             body.email_address, body.password)

    row = db.execute(text("""
        INSERT INTO personal_mailbox_accounts
            (user_id, label, imap_host, imap_port, imap_ssl, email_address,
             cred_enc, status, last_error)
        VALUES (:uid, :label, :host, :port, :ssl, :email, :cred, :status, :err)
        RETURNING id, user_id, label, imap_host, imap_port, imap_ssl,
                  email_address, status, last_error, last_poll_at, last_uid,
                  created_at, updated_at
    """), {
        "uid": uid, "label": body.label, "host": body.imap_host,
        "port": body.imap_port, "ssl": body.imap_ssl,
        "email": body.email_address.lower(), "cred": cred_enc,
        "status": status, "err": last_error,
    }).fetchone()
    db.commit()
    return dict(row._mapping)


@router.get("/personal-mailboxes/{account_id}")
def get_mailbox(account_id: int, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    row = _get_account_or_404(db, account_id, int(admin["id"]))
    return _row_to_public(row)


@router.put("/personal-mailboxes/{account_id}")
def update_mailbox(account_id: int, body: MailboxUpdate,
                   db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    uid = int(admin["id"])
    row = _get_account_or_404(db, account_id, uid)

    new_host = body.imap_host or row["imap_host"]
    new_port = body.imap_port or row["imap_port"]
    new_ssl = body.imap_ssl if body.imap_ssl is not None else row["imap_ssl"]
    new_email = (body.email_address or row["email_address"]).lower()
    new_label = body.label or row["label"]

    if body.password:
        cred_enc = encrypt_credentials({"user": new_email, "pass": body.password})
        password_for_test = body.password
    else:
        # Re-encrypt with existing credentials if host/email changed
        cred_enc = row["cred_enc"]
        try:
            existing_creds = decrypt_credentials(cred_enc)
            password_for_test = existing_creds["pass"]
        except Exception:
            raise HTTPException(400, "Cannot re-validate: stored credentials unreadable. Provide password.")

    status, last_error = _validate_and_test(new_host, new_port, new_ssl, new_email, password_for_test)

    db.execute(text("""
        UPDATE personal_mailbox_accounts
        SET label=:label, imap_host=:host, imap_port=:port, imap_ssl=:ssl,
            email_address=:email, cred_enc=:cred, status=:status,
            last_error=:err, updated_at=now()
        WHERE id=:id AND user_id=:uid
    """), {
        "label": new_label, "host": new_host, "port": new_port, "ssl": new_ssl,
        "email": new_email, "cred": cred_enc, "status": status, "err": last_error,
        "id": account_id, "uid": uid,
    })
    db.commit()
    updated = _get_account_or_404(db, account_id, uid)
    return _row_to_public(updated)


@router.delete("/personal-mailboxes/{account_id}", status_code=204)
def delete_mailbox(account_id: int, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    uid = int(admin["id"])
    _get_account_or_404(db, account_id, uid)  # 404 guard
    db.execute(text("""
        DELETE FROM personal_mailbox_accounts WHERE id=:id AND user_id=:uid
    """), {"id": account_id, "uid": uid})
    db.commit()


@router.post("/personal-mailboxes/{account_id}/test-connection")
def test_connection(account_id: int, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    uid = int(admin["id"])
    row = _get_account_or_404(db, account_id, uid)
    try:
        creds = decrypt_credentials(row["cred_enc"])
    except Exception as e:
        raise HTTPException(500, f"Cannot decrypt credentials: {e}")

    ok, err = personal_imap.test_login({
        "imap_host": row["imap_host"],
        "imap_port": row["imap_port"],
        "imap_ssl": row["imap_ssl"],
        "email_address": row["email_address"],
        "_password": creds["pass"],
    })
    new_status = "active" if ok else "error"
    db.execute(text("""
        UPDATE personal_mailbox_accounts
        SET status=:status, last_error=:err, updated_at=now()
        WHERE id=:id AND user_id=:uid
    """), {"status": new_status, "err": err, "id": account_id, "uid": uid})
    db.commit()
    return {"ok": ok, "status": new_status, "error": err}


# ── E2E inject test (IMAP APPEND → poller picks up within ~1 min) ────────────

@router.post("/personal-mailboxes/{account_id}/inject-test")
def inject_test(
    account_id: int,
    scenario: str,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    """Inject a synthetic RFC 2822 mail into INBOX via IMAP APPEND.
    Poller classifies and moves it within ~1 minute.
    scenario: quarantine|spam
    """
    if scenario not in ("quarantine", "spam"):
        raise HTTPException(400, "scenario must be 'quarantine' or 'spam'")
    uid = int(admin["id"])
    row = _get_account_or_404(db, account_id, uid)
    try:
        creds = decrypt_credentials(row["cred_enc"])
    except Exception as e:
        raise HTTPException(500, f"Cannot decrypt credentials: {e}")

    ok, msg, imap_uid = personal_imap.inject_test_mail(row, creds["pass"], scenario)
    if not ok:
        raise HTTPException(502, f"IMAP inject failed: {msg}")
    return {"ok": True, "scenario": scenario, "message": msg, "imap_uid": imap_uid}


# ── Detection smoke-test ──────────────────────────────────────────────────────

_SYNTHETIC_MAILS = {
    "quarantine": {
        "from_address": "security-alert@micros0ft-verify.com",
        "from_name": "Microsoft Security",
        "subject": "Urgent: resetează parola contului tău acum",
        "body_text": (
            "Contul tău a fost suspendat. Resetează imediat parola accesând link-ul de mai jos.\n"
            "Click aici: http://192.168.1.1/login/verify?token=abc123\n"
            "Acțiune necesară în 24 ore sau contul va fi blocat permanent."
        ),
        "body_html": "",
    },
    "spam": {
        "from_address": "promotions@bulk-offers-newsletter.com",
        "from_name": "Super Oferte",
        "subject": "🎉 CÂȘTIGĂ acum! Ofertă limitată — URGENT răspunde!",
        "body_text": (
            "Felicitări! Ai fost selectat pentru oferta noastră exclusivă!\n"
            "Cumpără acum și primești 90% reducere. Stoc limitat!\n"
            "Dezabonează-te: http://bit.ly/unsub999\n"
            "URGENT — oferta expiră AZI! Acționează RIGHT NOW!"
        ),
        "body_html": "",
    },
}


@router.post("/personal-mailboxes/{account_id}/test-detection")
def test_detection(
    account_id: int,
    scenario: str,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    """Run detection on a synthetic email (no IMAP, no DB write). scenario: quarantine|spam."""
    if scenario not in _SYNTHETIC_MAILS:
        from fastapi import HTTPException as _HTTPException
        raise _HTTPException(400, "scenario must be 'quarantine' or 'spam'")

    uid = int(admin["id"])
    _get_account_or_404(db, account_id, uid)  # 404 guard + ownership check

    email_dict = dict(_SYNTHETIC_MAILS[scenario])

    from app.services import phishing_detector, spam_detector
    from app.services.personal_mail_processor import SPAM_THRESHOLD

    try:
        _score, ph_status, ph_reasons = phishing_detector.detect_phishing(
            email_dict, attachments=[], suppress_codes=set(),
            blacklist=None, whitelist=None,
        )
    except Exception as exc:
        ph_status, ph_reasons = "clean", []

    try:
        spam_score, spam_reasons = spam_detector.detect_spam(email_dict)
    except Exception:
        spam_score, spam_reasons = 0.0, []

    if ph_status in ("quarantined", "quarantined_strict"):
        verdict = "quarantined"
        folder_action = "move_quarantine"
        reasons = ph_reasons
    elif spam_score >= SPAM_THRESHOLD:
        verdict = "spam"
        folder_action = "move_spam"
        reasons = spam_reasons
    else:
        verdict = "clean"
        folder_action = "none"
        reasons = ph_reasons + spam_reasons

    return {
        "scenario": scenario,
        "verdict": verdict,
        "folder_action": folder_action,
        "spam_score": spam_score,
        "ph_status": ph_status,
        "reasons": reasons,
        "synthetic_mail": {
            "from": email_dict["from_address"],
            "subject": email_dict["subject"],
        },
    }


# ── Poll trigger (used by systemd timer via curl) ─────────────────────────────

@router.post("/personal-mailboxes/poll", include_in_schema=False)
def trigger_poll():
    """Trigger poll for all due accounts. Called by cargo360-personal-poll.service."""
    from app.services import personal_mailbox_poller
    return personal_mailbox_poller.run()

# ── Reguli personale: blacklist / whitelist izolat de CTS ─────────────────────
# Cheie KV separată de 'phishing_manual_learning' (CTS) — fără impact cross.

import json as _json
from datetime import datetime as _datetime, timezone as _timezone
from fastapi import Query as _Query
from app.services.sender_lists import normalize as _normalize, entry_tip as _entry_tip, LISTS as _LISTS, TIPS as _TIPS

_PERSONAL_KEY = "personal_phishing_manual_learning"


def _pl_load(db: Session) -> dict:
    row = db.execute(text("SELECT value FROM settings WHERE key=:k"), {"k": _PERSONAL_KEY}).fetchone()
    store = (row[0] if row and row[0] else {}) or {}
    for lst in _LISTS:
        if not isinstance(store.get(lst), dict):
            store[lst] = {}
    return store


def _pl_save(db: Session, store: dict, by: str) -> None:
    db.execute(text(
        "INSERT INTO settings(key, value, description, updated_by, updated_at) "
        "VALUES(:k, CAST(:v AS jsonb), 'Reguli personale mailbox: blacklist + whitelist', :by, NOW()) "
        "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_by=:by, updated_at=NOW()"
    ), {"k": _PERSONAL_KEY, "v": _json.dumps(store), "by": by})


def _pl_entry_out(value: str, meta: dict) -> dict:
    meta = meta or {}
    _key, scope = _normalize(value)
    source = meta.get("source") or "manual"
    return {
        "value": value,
        "scope": scope or "domain",
        "by": meta.get("by"),
        "at": meta.get("at"),
        "muted": bool(meta.get("muted")),
        "note": meta.get("note"),
        "source": source,
        "tip": _entry_tip(meta),
    }


@router.get("/personal-mailboxes/rules/sender-lists")
def pl_get_sender_lists(db: Session = Depends(get_db), _admin=Depends(get_current_admin)):
    store = _pl_load(db)
    result = {}
    for lst in _LISTS:
        items = [_pl_entry_out(k, v) for k, v in (store.get(lst) or {}).items()]
        items.sort(key=lambda e: (e["muted"], e["value"]))
        result[lst] = items
    result["counts"] = {lst: len(result[lst]) for lst in _LISTS}
    return result


@router.post("/personal-mailboxes/rules/sender-lists")
def pl_add_sender_list(body: dict, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    reviewer = admin.get("username") or admin.get("email") or "admin"
    lst = (body.get("list") or "").strip().lower()
    if lst not in _LISTS:
        raise HTTPException(400, "Listă invalidă (blacklist/whitelist)")
    tip = (body.get("tip") or "").strip().lower() or None
    if tip and tip not in _TIPS:
        raise HTTPException(400, "Tip invalid (carantina/spam)")
    key, scope = _normalize(body.get("value") or "")
    if not key:
        raise HTTPException(400, "Valoare goală")
    store = _pl_load(db)
    other = "whitelist" if lst == "blacklist" else "blacklist"
    if key in (store.get(other) or {}):
        raise HTTPException(409, f"Valoarea există deja în '{other}'. Șterge-o întâi.")
    entry = dict((store.get(lst) or {}).get(key) or {})
    entry.setdefault("by", reviewer)
    entry.setdefault("at", _datetime.now(_timezone.utc).isoformat())
    entry.setdefault("source", "manual")
    entry.setdefault("muted", False)
    if body.get("note") is not None:
        entry["note"] = body["note"]
    if lst == "blacklist":
        t = (tip or "").strip().lower()
        if t in _TIPS:
            entry["tip"] = t
        elif "tip" not in entry:
            entry["tip"] = "carantina"
    store[lst][key] = entry
    _pl_save(db, store, reviewer)
    db.commit()
    return {"ok": True, "list": lst, "value": key, "scope": scope}


@router.put("/personal-mailboxes/rules/sender-lists")
def pl_edit_sender_list(body: dict, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    reviewer = admin.get("username") or admin.get("email") or "admin"
    lst = (body.get("list") or "").strip().lower()
    if lst not in _LISTS:
        raise HTTPException(400, "Listă invalidă")
    tip = (body.get("tip") or "").strip().lower() or None
    if tip and tip not in _TIPS:
        raise HTTPException(400, "Tip invalid (carantina/spam)")
    key, _ = _normalize(body.get("value") or "")
    store = _pl_load(db)
    bucket = store.get(lst) or {}
    if key not in bucket:
        raise HTTPException(404, "Intrare inexistentă")
    entry = dict(bucket[key])
    if body.get("muted") is not None:
        entry["muted"] = bool(body["muted"])
    if body.get("note") is not None:
        entry["note"] = body["note"]
    if tip and lst == "blacklist":
        entry["tip"] = tip
    new_value = body.get("new_value")
    target = key
    if new_value:
        nk, _ = _normalize(new_value)
        if nk and nk != key:
            other = "whitelist" if lst == "blacklist" else "blacklist"
            if nk in (store.get(other) or {}):
                raise HTTPException(400, "Valoarea există deja în lista opusă")
            if nk in bucket:
                raise HTTPException(400, "Valoarea există deja în această listă")
            del bucket[key]
            target = nk
    bucket[target] = entry
    store[lst] = bucket
    _pl_save(db, store, reviewer)
    db.commit()
    return {"ok": True, "value": target}


@router.delete("/personal-mailboxes/rules/sender-lists")
def pl_delete_sender_list(
    list: str = _Query(...),
    value: str = _Query(...),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    reviewer = admin.get("username") or admin.get("email") or "admin"
    if list not in _LISTS:
        raise HTTPException(400, "Listă invalidă")
    key, _ = _normalize(value)
    store = _pl_load(db)
    if key not in (store.get(list) or {}):
        raise HTTPException(404, "Intrare inexistentă")
    del store[list][key]
    _pl_save(db, store, reviewer)
    db.commit()
    return {"ok": True, "removed": key}


# ── Reguli per-cont: blacklist / whitelist izolate per account_id ──────────────

_ACCOUNT_SL_KEY = "personal_mailbox_senderlist_{}"


def _acct_sl_load(db: Session, account_id: int) -> dict:
    key = _ACCOUNT_SL_KEY.format(account_id)
    row = db.execute(text("SELECT value FROM settings WHERE key=:k"), {"k": key}).fetchone()
    store = (row[0] if row and row[0] else {}) or {}
    for lst in _LISTS:
        if not isinstance(store.get(lst), dict):
            store[lst] = {}
    return store


def _acct_sl_save(db: Session, account_id: int, store: dict, by: str) -> None:
    key = _ACCOUNT_SL_KEY.format(account_id)
    db.execute(text(
        "INSERT INTO settings(key, value, description, updated_by, updated_at) "
        "VALUES(:k, CAST(:v AS jsonb), :desc, :by, NOW()) "
        "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_by=:by, updated_at=NOW()"
    ), {"k": key, "v": _json.dumps(store), "desc": f"Sender lists cont {account_id}", "by": by})


@router.get("/personal-mailboxes/{account_id}/sender-lists")
def acct_get_sender_lists(account_id: int, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    uid = int(admin["id"])
    _get_account_or_404(db, account_id, uid)
    store = _acct_sl_load(db, account_id)
    result = {}
    for lst in _LISTS:
        items = [_pl_entry_out(k, v) for k, v in (store.get(lst) or {}).items()]
        items.sort(key=lambda e: (e["muted"], e["value"]))
        result[lst] = items
    result["counts"] = {lst: len(result[lst]) for lst in _LISTS}
    return result


@router.post("/personal-mailboxes/{account_id}/sender-lists")
def acct_add_sender_list(account_id: int, body: dict, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    uid = int(admin["id"])
    _get_account_or_404(db, account_id, uid)
    reviewer = admin.get("username") or admin.get("email") or "admin"
    lst = (body.get("list") or "").strip().lower()
    if lst not in _LISTS:
        raise HTTPException(400, "Listă invalidă (blacklist/whitelist)")
    tip = (body.get("tip") or "").strip().lower() or None
    if tip and tip not in _TIPS:
        raise HTTPException(400, "Tip invalid (carantina/spam)")
    key, scope = _normalize(body.get("value") or "")
    if not key:
        raise HTTPException(400, "Valoare goală")
    store = _acct_sl_load(db, account_id)
    other = "whitelist" if lst == "blacklist" else "blacklist"
    if key in (store.get(other) or {}):
        raise HTTPException(409, f"Valoarea există deja în '{other}'. Șterge-o întâi.")
    entry = dict((store.get(lst) or {}).get(key) or {})
    entry.setdefault("by", reviewer)
    entry.setdefault("at", _datetime.now(_timezone.utc).isoformat())
    entry.setdefault("source", "manual")
    entry.setdefault("muted", False)
    if body.get("note") is not None:
        entry["note"] = body["note"]
    if lst == "blacklist":
        t = (tip or "").strip().lower()
        entry["tip"] = t if t in _TIPS else "carantina"
    store[lst][key] = entry
    _acct_sl_save(db, account_id, store, reviewer)
    db.commit()
    return {"ok": True, "list": lst, "value": key, "scope": scope}


@router.put("/personal-mailboxes/{account_id}/sender-lists")
def acct_edit_sender_list(account_id: int, body: dict, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    uid = int(admin["id"])
    _get_account_or_404(db, account_id, uid)
    reviewer = admin.get("username") or admin.get("email") or "admin"
    lst = (body.get("list") or "").strip().lower()
    if lst not in _LISTS:
        raise HTTPException(400, "Listă invalidă")
    tip = (body.get("tip") or "").strip().lower() or None
    if tip and tip not in _TIPS:
        raise HTTPException(400, "Tip invalid (carantina/spam)")
    key, _ = _normalize(body.get("value") or "")
    store = _acct_sl_load(db, account_id)
    bucket = store.get(lst) or {}
    if key not in bucket:
        raise HTTPException(404, "Intrare inexistentă")
    entry = dict(bucket[key])
    if body.get("muted") is not None:
        entry["muted"] = bool(body["muted"])
    if body.get("note") is not None:
        entry["note"] = body["note"]
    if tip and lst == "blacklist":
        entry["tip"] = tip
    new_value = body.get("new_value")
    target = key
    if new_value:
        nk, _ = _normalize(new_value)
        if nk and nk != key:
            other = "whitelist" if lst == "blacklist" else "blacklist"
            if nk in (store.get(other) or {}):
                raise HTTPException(400, "Valoarea există deja în lista opusă")
            if nk in bucket:
                raise HTTPException(400, "Valoarea există deja în această listă")
            del bucket[key]
            target = nk
    bucket[target] = entry
    store[lst] = bucket
    _acct_sl_save(db, account_id, store, reviewer)
    db.commit()
    return {"ok": True, "value": target}


@router.delete("/personal-mailboxes/{account_id}/sender-lists")
def acct_delete_sender_list(
    account_id: int,
    list: str = _Query(...),
    value: str = _Query(...),
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    uid = int(admin["id"])
    _get_account_or_404(db, account_id, uid)
    reviewer = admin.get("username") or admin.get("email") or "admin"
    if list not in _LISTS:
        raise HTTPException(400, "Listă invalidă")
    key, _ = _normalize(value)
    store = _acct_sl_load(db, account_id)
    if key not in (store.get(list) or {}):
        raise HTTPException(404, "Intrare inexistentă")
    del store[list][key]
    _acct_sl_save(db, account_id, store, reviewer)
    db.commit()
    return {"ok": True, "removed": key}
