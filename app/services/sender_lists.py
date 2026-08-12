"""Liste de expeditori pentru detecție: blacklist + whitelist marcate de operator.

Store canonic UNIC: settings['phishing_manual_learning'].{blacklist, whitelist}.
  - blacklist : consumat de phishing_detector ca semnal Layer-4 DECISIV (enforcement hard).
  - whitelist : consumat SOFT de detector — suprimă semnalele slabe (L1/L2, non-malware),
                NICIODATĂ codurile malware/strict-decisive. Blacklist bate whitelist.

INVARIANT: cheia dict = valoarea normalizată (email complet SAU domeniu bare, fără '@').
NU schimba formatul cheii — consumatorul live face `saddr in bl or sdom in bl`. Câmpurile
auxiliare (muted/note/source/by/at/email_id) stau pe obiectul-valoare, nu în cheie.
"""
import json
from datetime import datetime, timezone

from sqlalchemy import text

_KEY = "phishing_manual_learning"
LISTS = ("blacklist", "whitelist")
TIPS = ("carantina", "spam")  # tip blacklist: ce detector consumă intrarea


def entry_tip(meta):
    """Tipul unei intrări de blacklist (carantina|spam), cu inferență back-compat pentru
    intrările fără câmpul `tip`: cele din confirmarea de spam (source=spam_confirm) → spam;
    restul (carantinare manuală / manual) → carantina."""
    meta = meta or {}
    t = (meta.get("tip") or "").strip().lower()
    if t in TIPS:
        return t
    return "spam" if meta.get("source") == "spam_confirm" else "carantina"


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def normalize(value):
    """Returnează (key, scope). key = email complet sau domeniu bare (fără '@')."""
    v = (value or "").strip().lower()
    if not v:
        return None, None
    if v.startswith("@"):
        return v[1:], "domain"
    if "@" in v:
        return v, "email"
    return v, "domain"


def _load(db):
    row = db.execute(text("SELECT value FROM settings WHERE key=:k"), {"k": _KEY}).fetchone()
    store = (row[0] if row and row[0] else {}) or {}
    for l in LISTS:
        if not isinstance(store.get(l), dict):
            store[l] = {}
    return store


def _save(db, store, by):
    db.execute(text(
        "INSERT INTO settings(key, value, description, updated_by, updated_at) "
        "VALUES(:k, CAST(:v AS jsonb), "
        "'Learning din carantinari manuale: blacklist + whitelist + exemple + propuneri', :by, NOW()) "
        "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_by=:by, updated_at=NOW()"),
        {"k": _KEY, "v": json.dumps(store), "by": by})


def _entry_out(value, meta):
    meta = meta or {}
    _key, scope = normalize(value)
    # Sursă: explicită dacă a fost setată; altfel deducem din intrările vechi
    # (cele scrise de learning-ul de carantinare manuală au email_id, fără source).
    source = meta.get("source")
    if not source:
        source = "quarantine" if meta.get("email_id") else "manual"
    return {
        "value": value,
        "scope": scope or "domain",
        "by": meta.get("by"),
        "at": meta.get("at"),
        "email_id": meta.get("email_id"),
        "muted": bool(meta.get("muted")),
        "note": meta.get("note"),
        "source": source,
        "tip": entry_tip(meta),
    }


def list_all(db):
    store = _load(db)
    out = {}
    for l in LISTS:
        items = [_entry_out(k, v) for k, v in (store.get(l) or {}).items()]
        items.sort(key=lambda e: (e["muted"], e["value"]))
        out[l] = items
    return out


def add_entry(db, list_name, value, by, email_id=None, source="manual", note=None,
              tip=None, commit=True):
    """Adaugă/actualizează o intrare. Returnează {ok}/{conflict}/{error}.

    Dacă valoarea e deja în lista OPUSĂ, NU o mută automat (respectă decizia umană) →
    returnează {"conflict": <lista_opusă>}.
    `tip` (carantina|spam) se aplică doar pe blacklist; whitelist îl ignoră.
    """
    if list_name not in LISTS:
        return {"error": "Listă invalidă"}
    key, scope = normalize(value)
    if not key:
        return {"error": "Valoare goală"}
    store = _load(db)
    other = "whitelist" if list_name == "blacklist" else "blacklist"
    if key in (store.get(other) or {}):
        return {"conflict": other, "value": key}
    existing = (store.get(list_name) or {}).get(key) or {}
    entry = dict(existing)
    entry.setdefault("by", by)
    entry.setdefault("at", _now_iso())
    if email_id is not None and not entry.get("email_id"):
        entry["email_id"] = email_id
    if note is not None:
        entry["note"] = note
    entry.setdefault("source", source)
    entry.setdefault("muted", False)
    if list_name == "blacklist":
        t = (tip or "").strip().lower()
        if t in TIPS:
            entry["tip"] = t
        elif "tip" not in entry:
            entry["tip"] = entry_tip(entry)  # inferență din source (spam_confirm→spam)
    store[list_name][key] = entry
    _save(db, store, by)
    if commit:
        db.commit()
    return {"ok": True, "list": list_name, "value": key, "scope": scope}


def remove_entry(db, list_name, value, by, commit=True):
    if list_name not in LISTS:
        return {"ok": False, "error": "Listă invalidă"}
    key, _ = normalize(value)
    store = _load(db)
    if key in (store.get(list_name) or {}):
        del store[list_name][key]
        _save(db, store, by)
        if commit:
            db.commit()
        return {"ok": True, "removed": key}
    return {"ok": False, "error": "Intrare inexistentă"}


def set_flags(db, list_name, value, by, muted=None, note=None, new_value=None,
              tip=None, commit=True):
    """Editează o intrare: mute/unmute, notă, redenumire valoare, tip (doar blacklist)."""
    if list_name not in LISTS:
        return {"ok": False, "error": "Listă invalidă"}
    key, _ = normalize(value)
    store = _load(db)
    bucket = store.get(list_name) or {}
    if key not in bucket:
        return {"ok": False, "error": "Intrare inexistentă"}
    entry = dict(bucket[key])
    if muted is not None:
        entry["muted"] = bool(muted)
    if note is not None:
        entry["note"] = note
    if tip is not None and list_name == "blacklist":
        t = (tip or "").strip().lower()
        if t in TIPS:
            entry["tip"] = t
    target = key
    if new_value:
        nk, _scope = normalize(new_value)
        if nk and nk != key:
            other = "whitelist" if list_name == "blacklist" else "blacklist"
            if nk in (store.get(other) or {}):
                return {"ok": False, "error": "Valoarea există deja în lista opusă"}
            if nk in bucket:
                return {"ok": False, "error": "Valoarea există deja în această listă"}
            del bucket[key]
            target = nk
    bucket[target] = entry
    store[list_name] = bucket
    _save(db, store, by)
    if commit:
        db.commit()
    return {"ok": True, "value": target}
