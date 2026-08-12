"""Dispecer auto-reply (DRY-RUN) + anti-spam throttle.

Doua declansatoare, ambele in dry-run (NU se trimite nimic; LOGAM decizia in `autoreply_send_log`,
outcome='would_send' la cele eligibile). Trimiterea reala (CTS-feed sau MS Graph) se cableaza ulterior
in `_transmit` — seam-ul e pregatit (AUTOREPLY_SEND_MODE).

  - trigger='new_in_cts' (Faza 1): un email NOU intra in CTS (`cts_update_emails`). Reply de PRELUARE.
    Refoloseste sugestia deja stocata in `emails.ai_autoreply` (+ confidence).
  - trigger='solved' (Faza 2): un email TRECE in 'solved' in CTS (detectat de cts_groundtruth_sync).
    Reply de INCHIDERE — generat ON-DEMAND cu autoreply_generator.generate_autoreply(kind='solved').
    Respecta optiunea CTS `cts_solved_auto_reply`: FALSE -> operatorul a raspuns manual, NU trimitem;
    TRUE/NULL -> eligibil (NULL = CTS inca nu trimite campul; strictetea e configurabila prin
    settings['autoreply.solved_requires_flag'], default False).

Eligibilitate comuna: flag AUTOREPLY_AUTOSEND_ENABLED activ; adresa valida; NU spam, NU expeditor
automat/intern (gate-urile din autoreply_generator); incredere >= prag (default 0.85);
ANTI-SPAM: max 1 'would_send'/'sent' per adresa expeditor in fereastra (default 10 min) — comuna
ambelor declansatoare (o adresa nu primeste 2 mailuri automate la <10 min, indiferent de tip).

Idempotent per (email, trigger): nu re-decidem acelasi email pe acelasi trigger (un 'new' nu blocheaza
un 'solved' ulterior si invers). Best-effort (NU rupe feed-ul CTS / sync-ul). Pragurile au cod-default +
override optional din `settings`: 'autoreply.send_confidence_min', 'autoreply.throttle_minutes'.
"""
import json
import logging
import os

import psycopg2
import psycopg2.extras

from app.config import get_settings

logger = logging.getLogger("mailguard.autoreply_dispatch")

settings = get_settings()

# Praguri — cod-default; override optional din settings.
DEFAULT_SEND_CONFIDENCE_MIN = 0.85
DEFAULT_THROTTLE_MINUTES = 10
SEND_CONF_KEY = "autoreply.send_confidence_min"
THROTTLE_MIN_KEY = "autoreply.throttle_minutes"
# Faza 2: daca True, un email solved fara flag CTS explicit (cts_solved_auto_reply IS NULL) NU primeste
# reply (asteptam ca CTS sa trimita TRUE). Default False: cat timp CTS inca nu trimite campul, NULL e
# tratat ca auto (bifa implicit pornita) -> putem valida mesajele de inchidere pe trafic real.
SOLVED_REQUIRES_FLAG_KEY = "autoreply.solved_requires_flag"

SPAM_THRESHOLD = 50  # oglinda process_email._is_spam_now / spam_detector

# Outcome-uri care CONSUMA fereastra de throttle (un mail catre acea adresa a "plecat").
_SENT_OUTCOMES = ["would_send", "sent"]


def _enabled() -> bool:
    v = (os.getenv("AUTOREPLY_AUTOSEND_ENABLED", "1") or "").strip().lower()
    return v not in ("0", "false", "no", "off", "")


def _send_mode() -> str:
    return (os.getenv("AUTOREPLY_SEND_MODE", "dry_run") or "dry_run").strip().lower()


def _conn():
    return psycopg2.connect(
        host=settings.db_host, port=settings.db_port,
        dbname=settings.db_name, user=settings.db_user, password=settings.db_password,
    )


def _setting_float(cur, key, default):
    """Citeste un numar din settings.value (jsonb): accepta numar sau string JSON. Fail-safe -> default."""
    try:
        cur.execute("SELECT value FROM settings WHERE key=%s", (key,))
        r = cur.fetchone()
        if not r:
            return default
        v = r["value"] if isinstance(r, dict) else r[0]
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            try:
                return float(json.loads(v))
            except Exception:
                return float(v.strip().strip('"'))
        return default
    except Exception:
        return default


def _send_confidence_min(cur) -> float:
    return max(0.0, min(1.0, _setting_float(cur, SEND_CONF_KEY, DEFAULT_SEND_CONFIDENCE_MIN)))


def _throttle_minutes(cur) -> int:
    try:
        return max(1, int(round(_setting_float(cur, THROTTLE_MIN_KEY, DEFAULT_THROTTLE_MINUTES))))
    except Exception:
        return DEFAULT_THROTTLE_MINUTES


def _setting_bool(cur, key, default: bool) -> bool:
    """Citeste un bool din settings.value (jsonb): accepta bool/numar/string. Fail-safe -> default."""
    try:
        cur.execute("SELECT value FROM settings WHERE key=%s", (key,))
        r = cur.fetchone()
        if not r:
            return default
        v = r["value"] if isinstance(r, dict) else r[0]
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return bool(v)
        if isinstance(v, str):
            s = v.strip().strip('"').lower()
            if s in ("1", "true", "yes", "on"):
                return True
            if s in ("0", "false", "no", "off"):
                return False
        return default
    except Exception:
        return default


def _solved_auto_reply_flag(cur, email_id):
    """Optiunea CTS 'trimite mail automat la solved' pentru acest email, din cts_ground_truth.
    True = bifa pornita; False = operatorul a raspuns manual (a ales template); None = CTS inca nu
    trimite campul. Best-effort -> None."""
    try:
        cur.execute(
            "SELECT cts_solved_auto_reply FROM cts_ground_truth "
            "WHERE email_id=%s ORDER BY last_synced_at DESC NULLS LAST LIMIT 1", (email_id,))
        r = cur.fetchone()
        if not r:
            return None
        return r["cts_solved_auto_reply"] if isinstance(r, dict) else r[0]
    except Exception:
        logger.exception("solved_auto_reply_flag failed email_id=%s", email_id)
        return None


def _is_spam(cur, email_id) -> bool:
    """Acelasi predicat ca process_email._is_spam_now (plasa de siguranta — spam-ul nu intra in feed clean)."""
    try:
        cur.execute("SELECT override, spam_score FROM email_spam WHERE email_id=%s", (email_id,))
        row = cur.fetchone()
        if not row:
            return False
        override = row["override"]
        score = row["spam_score"]
        if override is True:
            return True
        if override is False:
            return False
        return (score or 0) >= SPAM_THRESHOLD
    except Exception:
        logger.exception("is_spam check failed email_id=%s", email_id)
        return False


def _already_decided(cur, email_id, trigger) -> bool:
    """Idempotent per (email, trigger): un 'new' deja decis nu blocheaza un 'solved' ulterior."""
    cur.execute("SELECT 1 FROM autoreply_send_log WHERE email_id=%s AND trigger=%s "
                "AND outcome = ANY(%s) LIMIT 1",
                (email_id, trigger, _SENT_OUTCOMES))
    return cur.fetchone() is not None


def _recently_sent(cur, recipient, minutes) -> bool:
    """ANTI-SPAM: exista un would_send/sent catre aceasta adresa in ultimele `minutes` minute?"""
    cur.execute(
        "SELECT 1 FROM autoreply_send_log "
        "WHERE recipient=%s AND outcome = ANY(%s) "
        "AND created_at > now() - (%s || ' minutes')::interval LIMIT 1",
        (recipient, _SENT_OUTCOMES, str(minutes)))
    return cur.fetchone() is not None


def _log(cur, email_id, recipient, outcome, reason, confidence, text, send_mode, trigger):
    cur.execute(
        "INSERT INTO autoreply_send_log "
        "(email_id, recipient, trigger, outcome, reason, confidence, suggested_text, send_mode) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (email_id, recipient, trigger, outcome, reason, confidence, (text or None), send_mode))


def _transmit(email_id, recipient, text, send_mode, trigger="new_in_cts"):
    """Seam de trimitere. DRY-RUN: NU trimite nimic. Faza 1.5: 'cts_feed' / 'graph'."""
    if send_mode == "dry_run":
        return  # dry-run: doar logam would_send, fara transmitere reala
    # TODO Faza 1.5: 'cts_feed' (expune decizia+textul in feed-ul CTS, CTS trimite) /
    #                'graph' (POST /users/{MS_USER_EMAIL}/sendMail — necesita grant Mail.Send via outbox).
    raise NotImplementedError("AUTOREPLY_SEND_MODE=%s neimplementat (Faza 1.5)" % send_mode)


def _solved_text(cur, email_id, from_address, row):
    """Genereaza ON-DEMAND textul de INCHIDERE (kind='solved'). Intoarce (text, confidence) sau
    (None, reason) daca generarea nu reuseste (limba straina / incredere mica / AI indisponibil)."""
    from app.services import autoreply_generator as A
    gen = A.generate_autoreply({
        "id": email_id,
        "subject": row.get("subject"),
        "from_address": from_address,
        "from_name": row.get("from_name"),
        "body_text": row.get("body_text"),
        "body_html": row.get("body_html"),
        "conversation_id": row.get("conversation_id"),
    }, kind="solved")
    if not gen.get("ok"):
        return None, (gen.get("reason") or "fara sugestie de inchidere"), gen.get("confidence")
    return gen.get("text"), None, gen.get("confidence")


def dispatch_for_email(cur, email_id, trigger="new_in_cts", force=False) -> str:
    """Decide + (in dry-run) logheaza pentru un email. trigger='new_in_cts' (preluare, sugestie stocata)
    sau 'solved' (inchidere, text generat on-demand). Intoarce outcome-ul, sau '' daca s-a sarit fara
    log (dezactivat / deja decis / inexistent). Best-effort — caller-ul face commit/rollback."""
    from app.services import autoreply_generator as _ag
    if not _ag.autoreply_ai_status():
        return ""
    solved = (trigger == "solved")
    cur.execute(
        "SELECT subject, from_address, from_name, body_text, body_html, conversation_id, "
        "ai_autoreply, ai_autoreply_confidence, ai_autoreply_status "
        "FROM emails WHERE id=%s", (email_id,))
    row = cur.fetchone()
    if not row:
        return ""
    from_address = (row["from_address"] or "").strip()
    recipient = from_address.lower()
    send_mode = _send_mode()

    if not force and _already_decided(cur, email_id, trigger):
        return ""  # idempotent per (email, trigger)

    if not recipient or "@" not in recipient:
        _log(cur, email_id, recipient or "(necunoscut)", "skipped_ineligible",
             "fara adresa expeditor valida", None, None, send_mode, trigger)
        return "skipped_ineligible"

    # Expeditor automat / intern -> nu raspundem (reutilizam gate-urile generatorului).
    from app.services.autoreply_generator import _is_skip_sender, _is_internal_sender
    if _is_skip_sender(from_address) or _is_internal_sender(from_address):
        _log(cur, email_id, recipient, "skipped_ineligible", "expeditor automat/intern",
             None, None, send_mode, trigger)
        return "skipped_ineligible"

    if _is_spam(cur, email_id):
        _log(cur, email_id, recipient, "skipped_ineligible", "spam", None, None, send_mode, trigger)
        return "skipped_ineligible"

    # ── Sursa textului + verdicte specifice triggerului ──
    if solved:
        # Optiunea CTS: FALSE = operatorul a raspuns manual -> NU trimitem.
        flag = _solved_auto_reply_flag(cur, email_id)
        if flag is False:
            _log(cur, email_id, recipient, "skipped_ineligible",
                 "auto-reply dezactivat in CTS (operatorul a raspuns manual)", None, None, send_mode, trigger)
            return "skipped_ineligible"
        if flag is None and _setting_bool(cur, SOLVED_REQUIRES_FLAG_KEY, False):
            _log(cur, email_id, recipient, "skipped_ineligible",
                 "flag CTS solved_auto_reply absent (se cere TRUE explicit)", None, None, send_mode, trigger)
            return "skipped_ineligible"
        ai_text, gen_reason, conf = _solved_text(cur, email_id, from_address, row)
        if not (ai_text and ai_text.strip()):
            _log(cur, email_id, recipient, "skipped_ineligible",
                 "fara sugestie de inchidere: " + (gen_reason or ""), conf, None, send_mode, trigger)
            return "skipped_ineligible"
    else:
        ai_text = row["ai_autoreply"]
        conf = row["ai_autoreply_confidence"]
        # Verdictul operatorului are prioritate: respins -> nu trimitem.
        if row["ai_autoreply_status"] == "rejected":
            _log(cur, email_id, recipient, "skipped_ineligible", "operator a respins sugestia",
                 conf, ai_text, send_mode, trigger)
            return "skipped_ineligible"
        # Trebuie sa existe o sugestie (limba straina / fara continut sunt filtrate deja la generare).
        if not (ai_text and ai_text.strip()):
            _log(cur, email_id, recipient, "skipped_ineligible", "fara sugestie de reply",
                 conf, None, send_mode, trigger)
            return "skipped_ineligible"

    # Prag de incredere pentru AUTO-trimitere (mai strict decat pragul de stocare a sugestiei).
    conf_min = _send_confidence_min(cur)
    if conf is None or conf < conf_min:
        _log(cur, email_id, recipient, "skipped_confidence",
             "incredere %s sub pragul de auto-trimitere %.2f" % (
                 ("%.2f" % conf) if conf is not None else "necunoscuta", conf_min),
             conf, ai_text, send_mode, trigger)
        return "skipped_confidence"

    # ANTI-SPAM: max 1 reply automat / fereastra / adresa (comun ambelor declansatoare).
    minutes = _throttle_minutes(cur)
    if _recently_sent(cur, recipient, minutes):
        _log(cur, email_id, recipient, "throttled",
             "deja trimis un reply automat catre aceasta adresa in ultimele %d min" % minutes,
             conf, ai_text, send_mode, trigger)
        return "throttled"

    # Eligibil. In dry-run NU se transmite nimic; logam would_send (consuma si fereastra de throttle).
    _transmit(email_id, recipient, ai_text, send_mode, trigger)
    _log(cur, email_id, recipient, "would_send",
         "eligibil (dry-run: fara trimitere reala)" if send_mode == "dry_run" else "trimis",
         conf, ai_text, send_mode, trigger)
    return "would_send"


def dispatch_for_ids(ids, trigger="new_in_cts", force=False) -> dict:
    """Punct de intrare: decide pentru o lista de email-uri pe un trigger ('new_in_cts' din
    cts_update_emails, 'solved' din cts_groundtruth_sync). Conexiune proprie, commit per email (un esec
    izolat nu pierde restul). Ordine crescatoare a id-urilor (cel mai vechi intai) -> in caz de throttle,
    mailul cel mai vechi castiga 'would_send'. Best-effort."""
    if not _enabled():
        return {"enabled": False}
    try:
        ids = sorted({int(i) for i in ids if i is not None})
    except Exception:
        ids = []
    if not ids:
        return {"enabled": True, "trigger": trigger, "processed": 0, "counts": {}}
    counts = {}
    conn = None
    try:
        conn = _conn()
        for eid in ids:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                outcome = dispatch_for_email(cur, eid, trigger=trigger, force=force)
                conn.commit()
                if outcome:
                    counts[outcome] = counts.get(outcome, 0) + 1
            except Exception:
                conn.rollback()
                logger.exception("autoreply dispatch failed email_id=%s trigger=%s", eid, trigger)
            finally:
                cur.close()
    except Exception:
        logger.exception("autoreply dispatch_for_ids failed (trigger=%s)", trigger)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return {"enabled": True, "trigger": trigger, "processed": len(ids), "counts": counts}
