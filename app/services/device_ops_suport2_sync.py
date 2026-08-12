"""Sincronizare device_operations din view_device_operations (IRIS Data Views).

Inlocuieste sursa veche (/cts/device-operations, doar montatori) cu view_device_operations,
care expune Closed by/Closed at -- actorul Suport 2 care inchide operatia si momentul.

Filtrare: doar Status='Closed', Closed at >= CUTOFF_CLOSED_AT, Closed by rezolvat prin lookup
in employee_department_mapping (department IN suport_2/suport_3, case-insensitive+unaccent).
Operation Type fara mapare cunoscuta -> rand ignorat (nu eroare).

Truncate + repopulare completa la fiecare rulare (volum mic, ~1700 randuri/luna).
"""
import logging
import threading
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import SessionLocal
from app.api.v1.iris_dv import DV_BASE, _dv_headers, _get_api_key, _http_get_with_retry

logger = logging.getLogger(__name__)


def _parse_dv_ts(s: Optional[str]) -> Optional[datetime]:
    """view_device_operations trimite timestamps UTC cu offset RO aplicat gresit
    (bug IRIS DV confirmat 2026-08-06: '06:18+03:00' inseamna de fapt 06:18 UTC = 09:18 RO).
    Parsam ignorand offsetul si marcam explicit UTC."""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).strip())
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.replace(tzinfo=None).replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None

VIEW_NAME = "view_device_operations"
CUTOFF_CLOSED_AT = "2026-07-01"

# Cele 6 tipuri expuse de view_device_operations, plus variantele de denumire pentru ÎNLOCUIRE.
#
# ÎNLOCUIRE (verificat 2026-07-31, la cererea utilizatorului): tipul `inlocuire` NU e expus de
# `view_device_operations`. `Operation Type` are exact 6 valori distincte pe toate cele 70.069 de
# rânduri ale view-ului, iar niciuna nu e o înlocuire; nu există nici o coloană care să le
# distingă (21 output_columns) și nici un view alternativ (view_device_replacements/_replacement/
# _replacements/_operations_all/_ops -> toate 404). Cele 202 înlocuiri finalizate după cutoff
# există DOAR în sursa veche /cts/device-operations, ca action_type='inlocuire' cu operation_id
# prefixat `RP-` (218 în total din 1 iulie); `_row_id` din view-ul nou nu are prefixe, deci nu se
# pot corela nici prin id. Corelarea pe device a găsit doar 26 din 202, iar acelea apar în view ca
# Device Move/New Installation/Calibration — deci nici reclasificarea nu e o cale corectă.
#
# => Trebuie extins view-ul LA SURSĂ (cts_views.view_device_operations) ca să includă și
#    înlocuirile. Cheile de mai jos sunt pregătite pentru momentul în care apar, ca sincronizarea
#    să le preia fără redeploy: se acceptă mai multe denumiri plauzibile.
#    Cele nemapate NU se mai pierd silențios — vezi `unmapped_types` în rezultatul sync-ului.
OPERATION_TYPE_MAP = {
    "Device New Installation": "instalare_noua",
    "Device Move": "mutare",
    "Device Troubleshooting": "interventie",
    "Device Asset Calibration": "calibrare",
    "Device Add-On": "periferice",
    "Device Removal": "demontare",
    # Înlocuire — denumiri acceptate în avans (încă neprezente în view, vezi nota de mai sus).
    "Device Replacement": "inlocuire",
    "Device Replace": "inlocuire",
    "Device Exchange": "inlocuire",
    "Device Swap": "inlocuire",
}

_SUPORT2_DEPTS = ("suport_2", "suport_3")


def _fetch_all_rows(api_key: str) -> list:
    """Paginare completa /data. Continua pe baza next_cursor prezent -- NU pe has_more
    (poate fi None cu date ramase, bug confirmat live pe acest view)."""
    all_rows = []
    cursor = None
    page_num = 0
    while True:
        params = {"limit": "10000"}
        if cursor:
            params["cursor"] = cursor
        resp = httpx.get(
            f"{DV_BASE}/{VIEW_NAME}/data",
            params=params,
            headers=_dv_headers(api_key),
            timeout=60,
            follow_redirects=True,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"{VIEW_NAME}/data raspuns {resp.status_code}: {resp.text[:200]}")

        payload = resp.json()
        rows = payload if isinstance(payload, list) else payload.get("rows", [])
        cursor = payload.get("next_cursor") if isinstance(payload, dict) else None

        all_rows.extend(rows)
        page_num += 1
        logger.info("device_ops_suport2_sync: pagina %d, %d randuri acum", page_num, len(all_rows))

        if not rows or not cursor:
            break

    return all_rows


def _resolve_employee_by_name(db_session: Session, closed_by: Optional[str]) -> Optional[int]:
    """Rezolvă „Closed by" (text liber din view) la un angajat Suport 2/3.

    ORDINEA NUMELOR DIFERĂ ÎNTRE SURSE (verificat 2026-07-31): view-ul trimite „Robert Kovacs",
    iar `employee_department_mapping` are „Kovacs Robert". Egalitatea exactă potrivea doar 1 din 7
    angajați (Baican Emanuel-Crinel, singurul cu aceeași ordine în ambele surse), deci sincronizarea
    scria 3 rânduri din ~1810 eligibile — iar `TRUNCATE`-ul de la începutul sync-ului ștergea restul.
    Comparăm pe MULȚIMEA de cuvinte ale numelui, deci ordinea nu mai contează.

    Ambiguitatea e respinsă explicit: dacă aceeași mulțime de cuvinte duce la mai mulți angajați,
    întoarcem None (mai bine un rând ignorat decât o operațiune pusă în contul altcuiva — intră în
    calculul de productivitate).
    """
    if not closed_by or not closed_by.strip():
        return None
    # Numele compuse sunt scrise PARTIAL in view: "David Miclau" vs "Miclau Adrian-David",
    # "Ovidiu Ticus" vs "Ticus Ovidiu Alexandru", "Robert Iova" vs "Iova Oliviu-Robert".
    # Cratima se trateaza ca separator (Oliviu-Robert -> {oliviu, robert}), iar potrivirea cere ca
    # TOATE cuvintele din "Closed by" sa existe in numele angajatului (subset), nu egalitate.
    rows = db_session.execute(text("""
        WITH src AS (
          SELECT array_agg(w) AS words FROM unnest(
            string_to_array(regexp_replace(lower(unaccent(:n)), '[^a-z]+', ' ', 'g'), ' ')
          ) AS w WHERE w <> ''
        ), emp AS (
          SELECT m.id, (SELECT array_agg(w) FROM unnest(
                   string_to_array(regexp_replace(lower(unaccent(m.name)), '[^a-z]+', ' ', 'g'), ' ')
                 ) AS w WHERE w <> '') AS words
          FROM employee_department_mapping m
          WHERE m.department = ANY(:depts)
        )
        SELECT emp.id FROM emp, src
        WHERE cardinality(src.words) > 0
          AND src.words <@ emp.words      -- toate cuvintele din Closed by apar in numele angajatului
        LIMIT 2
    """), {"depts": list(_SUPORT2_DEPTS), "n": closed_by.strip()}).fetchall()
    return rows[0][0] if len(rows) == 1 else None


def _filter_and_map(db_session: Session, rows: list, unmapped: Optional[dict] = None) -> list:
    """Filtrează + mapează rândurile view-ului. `unmapped` (dict opțional) se populează cu
    tipurile de operațiune ELIGIBILE (închise, după cutoff, cu angajat Suport 2 rezolvat) pe care
    maparea nu le cunoaște. Fără el, un tip nou apărut la sursă dispare silențios — exact modul în
    care „Înlocuire" ar trece neobservat dacă view-ul ar începe să o expună sub altă denumire.
    """
    cutoff_dt = datetime.fromisoformat(CUTOFF_CLOSED_AT).replace(tzinfo=timezone.utc)
    out = []
    for r in rows:
        if r.get("Status") != "Closed":
            continue
        closed_at = _parse_dv_ts(r.get("Closed at"))
        if not closed_at or closed_at < cutoff_dt:
            continue
        emp_id = _resolve_employee_by_name(db_session, r.get("Closed by"))
        if emp_id is None:
            continue
        op_type_raw = r.get("Operation Type")
        action_type = OPERATION_TYPE_MAP.get(op_type_raw)
        if action_type is None:
            if unmapped is not None:
                k = str(op_type_raw)
                unmapped[k] = unmapped.get(k, 0) + 1
            continue

        out.append({
            "operation_id": r.get("_row_id"),
            "dv_row_id": r.get("_row_id"),
            "action_type": action_type,
            "operation_type_raw": op_type_raw,
            "status": "finalizat",
            "terminal": True,
            "closed_by_raw": r.get("Closed by"),
            "closed_by_employee_id": emp_id,
            "closed_at": closed_at,
            "finished_at": _parse_dv_ts(r.get("Finished at")),
            "assignee_raw": r.get("Closed by"),
            "assignee_employee_id": emp_id,
            "department": "suport_2",
            "client_name": r.get("Client"),
            "device_serial": r.get("Device"),
            "device_imei": r.get("Device ID"),
            "description": r.get("Description") or r.get("Notes"),
            "cts_created_at": None,
            "cts_updated_at": closed_at,
        })
    return out


_INSERT_SQL = text("""
    INSERT INTO device_operations (
        operation_id, dv_row_id, action_type, operation_type_raw, status, terminal,
        closed_by_raw, closed_by_employee_id, closed_at, finished_at,
        assignee_raw, assignee_employee_id, department, client_name, device_serial, device_imei,
        description, cts_created_at, cts_updated_at, source, first_synced_at, last_synced_at,
        created_at, updated_at
    ) VALUES (
        :operation_id, :dv_row_id, :action_type, :operation_type_raw, :status, :terminal,
        :closed_by_raw, :closed_by_employee_id, :closed_at, :finished_at,
        :assignee_raw, :assignee_employee_id, :department, :client_name, :device_serial, :device_imei,
        :description, :cts_created_at, :cts_updated_at, 'iris_dv_suport2', :now, :now, :now, :now
    )
    ON CONFLICT (operation_id) DO NOTHING
""")


def run_full_sync(db: Session) -> dict:
    """Truncate + repopulare device_operations din view_device_operations (whitelist Suport 2)."""
    api_key = _get_api_key(db)
    if not api_key:
        return {"ok": False, "error": "Cheia API IRIS Data Views nu este configurata."}

    try:
        raw_rows = _fetch_all_rows(api_key)
        unmapped: dict = {}
        mapped = _filter_and_map(db, raw_rows, unmapped)

        # GARDĂ ANTI-GOLIRE (adăugată 2026-07-31 după un incident real): sync-ul face TRUNCATE
        # înainte de repopulare, deci o regresie în filtrare nu doar aduce mai puțin — ȘTERGE ce
        # era bun. S-a întâmplat: potrivirea numelor a picat de la ~1810 la 3 rânduri și
        # TRUNCATE-ul a golit tabela. Dacă noul set e sub 50% din cel existent, NU rescriem nimic.
        existing = db.execute(text("SELECT count(*) FROM device_operations")).scalar() or 0
        if existing >= 20 and len(mapped) * 2 < existing:
            db.rollback()
            msg = ("Sync ABANDONAT ca masura de siguranta: sursa ar fi adus %d randuri, in baza "
                   "sunt %d (scadere >50%%). Datele existente au fost PASTRATE. Verifica filtrarea "
                   "(mapare tipuri / rezolvare 'Closed by') inainte de a relua." % (len(mapped), existing))
            logger.error("device_ops_suport2_sync: %s", msg)
            return {"ok": False, "error": msg, "would_write": len(mapped), "existing": existing,
                    "unmapped_types": unmapped}

        now = datetime.now(timezone.utc)
        db.execute(text("TRUNCATE TABLE device_operations"))
        for row in mapped:
            db.execute(_INSERT_SQL, {**row, "now": now})
        db.commit()

        # Tipurile din view care ar fi fost eligibile dar nu sunt cunoscute: le facem VIZIBILE
        # (log WARNING + in raspuns), ca sa nu se mai piarda silentios ca la "Inlocuire".
        if unmapped:
            logger.warning("device_ops_suport2_sync: tipuri de operatiune NEMAPATE, randuri "
                           "ignorate: %s", unmapped)
        # Tipurile cunoscute care au ajuns cu ZERO randuri: semnal ca sursa nu le (mai) expune.
        # `inlocuire` e aici din 2026-07-31 -- view_device_operations nu o expune deloc.
        present = {r["action_type"] for r in mapped}
        missing = sorted(set(OPERATION_TYPE_MAP.values()) - present)
        if missing:
            logger.warning("device_ops_suport2_sync: tipuri cunoscute cu 0 randuri in view: %s",
                           missing)

        logger.info("device_ops_suport2_sync: fetched=%d written=%d", len(raw_rows), len(mapped))
        return {"ok": True, "fetched": len(raw_rows), "written": len(mapped),
                "unmapped_types": unmapped, "missing_types": missing}
    except Exception as e:
        db.rollback()
        logger.exception("device_ops_suport2_sync: eroare")
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------- cron

LAST_RECENT_KEY = "device_ops_dv.last_recent_sync_at"
RECENT_MIN_INTERVAL_S = 3600   # o data/ora: sync-ul e TRUNCATE + repopulare completa (~70k randuri
                               # citite din view), nu incremental -- la 5 min ar fi risipa inutila.
_recent_lock = threading.Lock()


def _seconds_since_last(db) -> Optional[float]:
    row = db.execute(text("SELECT value FROM settings WHERE key=:k"),
                     {"k": LAST_RECENT_KEY}).fetchone()
    if not row or row[0] is None:
        return None
    try:
        ts = datetime.fromisoformat(str(row[0]).strip().strip('"'))
        return (datetime.utcnow() - ts.replace(tzinfo=None)).total_seconds()
    except Exception:
        return None


def run_recent_if_due() -> dict:
    """Apelat de cron (POST /process/run-now). Pana la 2026-07-31 sincronizarea rula DOAR manual,
    din buton: `device_ops.last_recent_sync_at` era blocat la 30 iulie 10:00 si `device_ops_dv`
    la 31 iulie 07:43 (=10:43 local) -- exact ce raporta utilizatorul ca "stuck". Niciunul din
    cele doua module device_ops nu era in blocul de cron din emails.py, desi restul (mailuri,
    apeluri, task-uri, pontaj) erau. Nu arunca niciodata.
    """
    try:
        if not _recent_lock.acquire(blocking=False):
            return {"ok": True, "skipped": "already_running"}
        try:
            db = SessionLocal()
            try:
                elapsed = _seconds_since_last(db)
                if elapsed is not None and elapsed < RECENT_MIN_INTERVAL_S:
                    return {"ok": True, "skipped": "throttled", "elapsed_s": int(elapsed)}
                db.execute(text(
                    "INSERT INTO settings(key, value, updated_by, updated_at) "
                    "VALUES (:k, CAST(:v AS jsonb), 'cron', now()) "
                    "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, "
                    "updated_by='cron', updated_at=now()"),
                    {"k": LAST_RECENT_KEY, "v": '"%s"' % datetime.utcnow().isoformat()})
                db.commit()
                res = run_full_sync(db)
                logger.info("device_ops_dv rolling sync: %s", res)
                return res
            finally:
                db.close()
        finally:
            _recent_lock.release()
    except Exception as e:
        logger.warning("device_ops_dv run_recent_if_due failed: %s", e)
        return {"ok": False, "error": str(e)[:200]}
