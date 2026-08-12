"""Match client by phone number — analog process_email.match_client() (match by email).

Numerele sunt normalizate la forma E.164-ish (doar cifre, prefix cu '+') înainte de căutare,
pentru ca formatul primit din While1 să nu depindă de cum a fost introdus în clients.phones.
"""
import re
from sqlalchemy import text
from app.database import SessionLocal


def normalize_phone(raw: str) -> str:
    """Păstrează doar cifrele + '+' inițial. '0722 123 456' -> '+40722123456' NU e dedus automat
    aici (fără prefix de țară cunoscut) — se normalizează doar formatul, nu se inventează prefixul."""
    if not raw:
        return ""
    digits = re.sub(r"[^\d+]", "", raw.strip())
    return digits


def phone_key(raw: str) -> str:
    """Cheie canonică de comparare: ultimele 9 cifre semnificative.

    Motiv: același abonat apare în surse diferite cu prefixe diferite — `0722123456`
    (local), `+40722123456` (E.164), `0040722123456` (00 international). Ultimele 9 cifre
    sunt identice în toate variantele, atât pentru RO (`722123456`) cât și pentru numerele
    din alte țări (MD `0037368295882` vs `+37368533883` -> `368295882` / `368533883`).
    Returnează "" dacă numărul are sub 9 cifre (extensii interne, junk de tip 'h').
    """
    digits = re.sub(r"\D", "", raw or "")
    return digits[-9:] if len(digits) >= 9 else ""


def match_client_by_phone(phone: str):
    """Caută clientul după numărul de telefon în clients.phones (jsonb array). Returnează
    client_id sau None. Mirror process_email.match_client (căutare pe emails.jsonb).

    Comparația se face pe cheia canonică (ultimele 9 cifre), nu pe string exact — altfel
    formatele diferite din While1 vs CTS nu se potrivesc. Dacă numărul se mapează pe mai
    mulți clienți (număr partajat), NU se întoarce niciunul: mai bine NULL decât atribuire
    greșită într-un calcul de satisfacție.
    """
    key = phone_key(phone)
    if not key:
        return None
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT DISTINCT k.client_id
            FROM client_phone_keys k
            JOIN clients c ON c.id = k.client_id AND c.is_active = TRUE
            WHERE k.phone_key = :k
            LIMIT 2
        """), {"k": key}).fetchall()
        return rows[0][0] if len(rows) == 1 else None
    finally:
        db.close()


def rebuild_client_unique_emails(db=None) -> int:
    """Reconstruiește client_unique_emails: adresele care identifică UNIC un client activ.

    O adresă prezentă la mai mulți clienți (furnizori, bănci, sau text liber de tip `dispecer`)
    nu identifică pe nimeni, deci nu intră. Folosită de satisfaction_engine ca să lege mailurile
    orfane fără să atribuie unui client interacțiunile altuia. Vezi migrația 20260729h.
    """
    own = db is None
    db = db or SessionLocal()
    try:
        db.execute(text("DELETE FROM client_unique_emails"))
        db.execute(text("""
            INSERT INTO client_unique_emails (client_id, email)
            WITH parts AS (
                SELECT c.id AS client_id, lower(trim(part)) AS addr
                FROM clients c,
                     jsonb_array_elements_text(c.emails) e,
                     unnest(string_to_array(e, ';')) AS part
                WHERE c.is_active
            ),
            counted AS (
                SELECT addr, count(DISTINCT client_id) AS n FROM parts GROUP BY 1
            )
            SELECT p.client_id, p.addr
            FROM parts p JOIN counted k ON k.addr = p.addr
            WHERE k.n = 1
              AND p.addr LIKE '%@%'
              AND length(p.addr) <= 320
              AND p.addr NOT LIKE '% %'
              AND p.addr NOT LIKE '%cargotrack.ro'
              AND p.addr NOT LIKE '%trakosoft.ro'
            ON CONFLICT DO NOTHING
        """))
        n = db.execute(text("SELECT count(*) FROM client_unique_emails")).scalar()
        db.commit()
        return int(n or 0)
    finally:
        if own:
            db.close()


def rebuild_phone_index(db=None) -> int:
    """Reconstruiește client_phone_keys din clients.phones. Idempotent.

    De apelat după orice sync care modifică clients.phones — altfel index-ul rămâne
    în urmă și apelurile clienților noi nu se mai leagă. Întoarce nr. de chei rezultate.
    """
    own = db is None
    db = db or SessionLocal()
    try:
        db.execute(text("DELETE FROM client_phone_keys"))
        db.execute(text("""
            INSERT INTO client_phone_keys (client_id, phone_key)
            SELECT c.id, right(regexp_replace(p, '\\D', '', 'g'), 9)
            FROM clients c, jsonb_array_elements_text(c.phones) p
            WHERE length(regexp_replace(p, '\\D', '', 'g')) >= 9
            ON CONFLICT DO NOTHING
        """))
        n = db.execute(text("SELECT count(*) FROM client_phone_keys")).scalar()
        db.commit()
        return int(n or 0)
    finally:
        if own:
            db.close()
