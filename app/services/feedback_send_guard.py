"""Gardă de siguranță — trimitere reală de feedback pe staging (T5+).

⛔ REGULĂ CRITICĂ, decisă manual de Raul Covaci (2026-07-16):
Pe serverul de staging NU se trimite NICIODATĂ email de feedback către un
client real. Singurele adrese pe care e permis să trimitem, pentru testare,
sunt:
    - raul.covaci@cargotrack.ro
    - raul.covaci@trakosoft.ro

Orice alt destinatar TREBUIE blocat înainte de a ajunge la un furnizor real
de email (SMTP/O365/etc). Această regulă nu se relaxează fără aprobare
manuală explicită din partea lui Raul — niciun agent, niciun task viitor
(T5 „trimitere efectivă a linkurilor", sau orice altă funcție care trimite
email către clienți din campaniile de feedback) nu are voie să treacă peste
ea sau să o șteargă fără cerere directă.

Orice cod nou care trimite emailuri de feedback către clienți TREBUIE să
apeleze `assert_send_allowed(to_address)` înainte de trimiterea efectivă.
"""
import logging
import os

logger = logging.getLogger("mailguard.feedback_send_guard")

# Whitelist staging — singurele adrese reale acceptate pentru testare.
STAGING_ALLOWED_RECIPIENTS = {
    "raul.covaci@cargotrack.ro",
    "raul.covaci@trakosoft.ro",
}


class FeedbackSendBlocked(Exception):
    """Ridicată când se încearcă trimiterea unui feedback către o adresă
    neautorizată pe mediul de staging."""


def _is_staging() -> bool:
    # MAILGUARD_ENV nu e încă definit explicit în proiect la 2026-07-16;
    # implicit considerăm staging (fail-safe: blochează, nu trimite),
    # doar dacă e setat explicit "production" se dezactivează garda.
    return os.environ.get("MAILGUARD_ENV", "staging").strip().lower() != "production"


def assert_send_allowed(to_address: str) -> None:
    """Oprește trimiterea de feedback pe staging spre orice adresă în afara
    whitelist-ului. Trebuie apelată chiar înainte de orice trimitere reală
    de email către un client, din orice task de campanie de feedback."""
    if not _is_staging():
        return
    normalized = (to_address or "").strip().lower()
    if normalized not in STAGING_ALLOWED_RECIPIENTS:
        logger.warning(
            "Trimitere feedback BLOCATĂ pe staging — adresă neautorizată: %s", normalized
        )
        raise FeedbackSendBlocked(
            f"Trimitere blocată pe staging: '{to_address}' nu e în whitelist-ul de test "
            f"({', '.join(sorted(STAGING_ALLOWED_RECIPIENTS))}). "
            "Nu se trimite niciun email de feedback către clienți reali pe staging."
        )
