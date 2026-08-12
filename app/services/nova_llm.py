"""Worklog summarizer — turns a code diff into a human-readable summary via IRIS.

Thin consumer of app.services.iris_ai: builds the system + user prompt from the
`prompts` table (code='backup_worklog') or built-in defaults, asks IRIS for a
plain-language bullet summary, and returns it as a list of strings.

Degrades gracefully: if IRIS AI is not configured or anything fails, returns []
and the worklog modal shows the file list instead of an AI summary.
"""
import logging
from sqlalchemy import text

from app.database import SessionLocal
from app.services import iris_ai

logger = logging.getLogger("mailguard.nova_llm")

PROMPT_CODE = "backup_worklog"

DEFAULT_SYSTEM = (
    "Ești un asistent care rezumă pe înțelesul oamenilor modificările aduse codului "
    "unei aplicații între două backup-uri. Primești lista fișierelor modificate și un diff "
    "tehnic. Produ un rezumat SCURT în limba română, ca listă de bullet points, descriind CE "
    "funcționalități/feature-uri s-au adăugat sau schimbat și de ce contează pentru utilizator. "
    "NU include linii de cod, nume de fișiere/variabile sau detalii de implementare. "
    "Maxim 6 bullet-uri, fiecare o propoziție clară."
)
DEFAULT_USER_TMPL = (
    "Fișiere modificate: {{FILES}}\n\n"
    "Diff tehnic (doar referință internă, NU îl cita):\n{{DIFF}}\n\n"
    "Scrie rezumatul în bullet points, limbaj uman:"
)
DEFAULT_MAX_TOKENS = 400


def _load_prompt():
    """Prompt config from DB if present, else built-in defaults."""
    try:
        db = SessionLocal()
        row = db.execute(text(
            "SELECT system_prompt, user_prompt_template, model, temperature, max_tokens "
            "FROM prompts WHERE code = :c AND is_active = true"
        ), {"c": PROMPT_CODE}).fetchone()
        db.close()
        if row:
            return dict(row._mapping)
    except Exception as e:
        logger.warning(f"prompt DB load failed, using defaults: {e}")
    return {
        "system_prompt": DEFAULT_SYSTEM,
        "user_prompt_template": DEFAULT_USER_TMPL,
        "model": None,
        "temperature": 0.2,
        "max_tokens": DEFAULT_MAX_TOKENS,
    }


def _parse_bullets(content: str):
    out = []
    for line in (content or "").splitlines():
        s = line.strip().lstrip("-*•").strip()
        if s[:2].rstrip(".)").isdigit():
            s = s.split(".", 1)[-1].split(")", 1)[-1].strip()
        if s:
            out.append(s)
    return out[:20]


def summarize(diff_text: str, files_changed) -> list:
    """Return a list of human-readable bullet strings, or [] if unavailable."""
    if not iris_ai.is_configured():
        return []  # not wired yet — graceful no-op

    p = _load_prompt()
    files = ", ".join(files_changed) if files_changed else "(niciun fișier)"
    user = (p["user_prompt_template"] or "").replace("{{FILES}}", files).replace("{{DIFF}}", diff_text or "")

    res = iris_ai.run_prompt(
        p["system_prompt"], user,
        response_format="text",
        model_hint=p.get("model"),
        temperature=float(p.get("temperature") or 0.2),
        max_tokens=int(p.get("max_tokens") or DEFAULT_MAX_TOKENS),
        task="cargo360:backup_worklog",
    )
    if not res.get("ok"):
        logger.warning("worklog summarize failed: %s", res.get("error"))
        return []
    return _parse_bullets(res.get("text"))
