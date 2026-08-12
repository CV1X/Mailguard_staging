"""Trimitere email campanii de feedback (T5) — SMTP, cu gardă de siguranță obligatorie.

Contul SMTP e configurat din UI (pagina Configurare KPI), stocat în tabela
`feedback_email_config` (single-row). Parola e criptată la repaus cu
`credential_crypto` (același mecanism folosit deja pentru credențialele IMAP
ale mailbox-urilor personale) — nu apare niciodată în clar în DB.

Orice trimitere reală TREBUIE să treacă prin `feedback_send_guard.assert_send_allowed`
înainte de conectarea SMTP — vezi acel modul pentru regula de business (whitelist
staging).
"""
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.credential_crypto import encrypt_credentials, decrypt_credentials
from app.services.feedback_send_guard import assert_send_allowed

logger = logging.getLogger("mailguard.feedback_email_sender")


class EmailConfigMissing(Exception):
    """Ridicată când nu există încă un cont SMTP configurat."""


def get_email_config(db: Session) -> Optional[dict]:
    row = db.execute(text("""
        SELECT id, smtp_host, smtp_port, smtp_user, smtp_pass_enc, from_address, use_tls
        FROM feedback_email_config ORDER BY id LIMIT 1
    """)).fetchone()
    return dict(row._mapping) if row else None


def save_email_config(db: Session, smtp_host: str, smtp_port: int, smtp_user: str,
                       from_address: str, use_tls: bool, smtp_password: Optional[str]) -> dict:
    """Salvează configul. Dacă `smtp_password` e None, păstrează parola existentă
    (permite editarea host/port/user fără să retastezi parola)."""
    existing = get_email_config(db)
    if smtp_password:
        pass_enc = encrypt_credentials({"password": smtp_password})
    elif existing:
        pass_enc = existing["smtp_pass_enc"]
    else:
        raise ValueError("Parola SMTP e obligatorie la prima configurare")

    if existing:
        db.execute(text("""
            UPDATE feedback_email_config
            SET smtp_host=:host, smtp_port=:port, smtp_user=:user, smtp_pass_enc=:pass_enc,
                from_address=:from_addr, use_tls=:use_tls, updated_at=now()
            WHERE id=:id
        """), {"host": smtp_host, "port": smtp_port, "user": smtp_user, "pass_enc": pass_enc,
                "from_addr": from_address, "use_tls": use_tls, "id": existing["id"]})
    else:
        db.execute(text("""
            INSERT INTO feedback_email_config (smtp_host, smtp_port, smtp_user, smtp_pass_enc, from_address, use_tls)
            VALUES (:host, :port, :user, :pass_enc, :from_addr, :use_tls)
        """), {"host": smtp_host, "port": smtp_port, "user": smtp_user, "pass_enc": pass_enc,
                "from_addr": from_address, "use_tls": use_tls})
    db.commit()
    return get_email_config(db)


def send_feedback_email(db: Session, to_address: str, subject: str, html_body: str) -> None:
    """Trimite un singur email de campanie. Verifică garda de siguranță ÎNAINTE
    de a deschide conexiunea SMTP — orice adresă în afara whitelist-ului pe
    staging e blocată aici, nu ajunge la server."""
    assert_send_allowed(to_address)

    cfg = get_email_config(db)
    if not cfg:
        raise EmailConfigMissing("Nu există cont SMTP configurat (Configurare KPI → Cont email)")
    password = decrypt_credentials(cfg["smtp_pass_enc"])["password"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = cfg["from_address"]
    msg["To"] = to_address
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"], timeout=15) as server:
        if cfg["use_tls"]:
            server.starttls()
        server.login(cfg["smtp_user"], password)
        server.sendmail(cfg["from_address"], [to_address], msg.as_string())

    logger.info("Feedback email trimis către %s", to_address)
