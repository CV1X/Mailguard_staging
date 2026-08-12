"""Rapoarte AI — pagina Rapoarte din sidebar.

Raport: GRUPARE EMAILURI AUTOMATE. Identifica emailurile standard generate automat de sisteme
(ex. alerte HU-GO/toll, notificari, confirmari) care sosesc repetat sub acelasi sablon si pot fi
procesate in lot. Fluxul cerut de utilizator:

  1. Se iau TOATE emailurile cu text si FARA atasamente din fereastra (data selectabila: since/until,
     default luna curenta).
  2. Emailurile care se potrivesc cu un PATTERN deja CONFIRMAT (lista „automate") sunt EXCLUSE din
     analiza (nu se mai trimit la AI) — sunt doar atribuite pattern-ului (acumuleaza email_ids).
  3. Restul se grupeaza determinist pe SimHash (template_fingerprint) per expeditor; fiecare grup
     recurent (>=2) e analizat o data de AI (use_cache+learn → reluari ~gratis).
  4. Utilizatorul bifeaza grupurile pe care le vrea „automate" -> /reports/patterns/confirm le muta
     in report_patterns (lista separata, persistenta). De acolo se vor dezvolta endpointurile de
     procesare. La urmatoarea regenerare aceste grupuri NU mai sunt analizate (sunt excluse la pasul 2).
"""
import re
import json
import time
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import get_db, SessionLocal
from app.api.v1.auth import get_current_admin
from app.services import iris_ai
from app.services import template_fingerprint as tfp

logger = logging.getLogger("mailguard.reports")
router = APIRouter()

REPORT_TYPE = "email_grouping"
PROMPT_VER = "v2"         # bumpeaza la editarea promptului AI → invalideaza cache-ul vechi
LEARN_SCOPE = "cargo360:report_grouping:" + PROMPT_VER
FP_HAMMING_K = 4          # cat de aproape trebuie sa fie 2 emailuri ca sa fie acelasi sablon
PATTERN_MATCH_K = 5       # toleranta la potrivirea cu un pattern confirmat (putin mai laxa)
MIN_CLUSTER = 2           # grup recurent = cel putin 2 emailuri
MAX_AI_CALLS = 400        # plafon apeluri AI per generare (acopera toate grupurile recurente)
MAX_FPS_PER_GROUP = 40    # cate fingerprint-uri reprezentative stocam per grup/pattern
AI_WORKERS = 3            # >3 paralele pe gateway-ul IRIS public → HTTP_502 in masa
STALE_SECONDS = 1800

_HTML_TAG = re.compile(r"(?is)<(script|style)[^>]*>.*?</\1>")
_TAGS = re.compile(r"(?s)<[^>]+>")
_WS = re.compile(r"\s+")


def _strip_html(html: str) -> str:
    s = _HTML_TAG.sub(" ", html or "")
    s = _TAGS.sub(" ", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&")
    return _WS.sub(" ", s).strip()


def _body_of(e: dict) -> str:
    bt = (e.get("body_text") or "").strip()
    if len(bt) >= 40:
        return bt
    hs = _strip_html(e.get("body_html") or "")
    return hs if len(hs) > len(bt) else (bt or hs)


def _fp_of(e: dict):
    return tfp.fingerprint((e.get("subject") or "") + "\n" + _body_of(e))


def _dedup_fps(fps: list, k: int = 2, cap: int = MAX_FPS_PER_GROUP) -> list:
    """Pastreaza fingerprint-uri reprezentative: elimina cele near-identice (Hamming<=k)."""
    kept = []
    for fp in fps:
        if fp is None:
            continue
        if any(tfp.hamming(fp, x) <= k for x in kept):
            continue
        kept.append(fp)
        if len(kept) >= cap:
            break
    return kept


# ── Pattern-uri confirmate (lista „automate") ───────────────────────────────
def _load_patterns(db: Session) -> list:
    rows = db.execute(text(
        "SELECT id, from_addresses, fingerprints, extract_enabled FROM report_patterns WHERE status='active'")).fetchall()
    out = []
    for r in rows:
        d = dict(r._mapping)
        fas = d.get("from_addresses") or []
        fps = d.get("fingerprints") or []
        out.append({
            "id": d["id"],
            "from_addrs": set((a or "").lower() for a in fas),
            "fps": [int(x) for x in fps],
            "extract_enabled": bool(d.get("extract_enabled")),
        })
    return out


def _match_pattern(from_addr: str, fp, patterns: list):
    """Returneaza id-ul primului pattern confirmat care se potriveste, altfel None."""
    fa = (from_addr or "").lower()
    for p in patterns:
        if p["from_addrs"] and fa not in p["from_addrs"]:
            continue
        if fp is None:
            continue
        if any(tfp.hamming(fp, pf) <= PATTERN_MATCH_K for pf in p["fps"]):
            return p["id"]
    return None


def _load_patterns_pg(cur) -> list:
    """Varianta psycopg2 a `_load_patterns` pentru pipeline-ul live (process_email).
    Construieste EXACT aceeasi forma de pattern, ca sa reutilizam `_match_pattern`
    (sursa unica de adevar pentru potrivire — fara drift fata de regenerare)."""
    cur.execute("SELECT id, from_addresses, fingerprints, extract_enabled "
                "FROM report_patterns WHERE status='active'")
    out = []
    for r in cur.fetchall():
        d = dict(r) if isinstance(r, dict) else {
            "id": r[0], "from_addresses": r[1], "fingerprints": r[2], "extract_enabled": r[3]}
        fas = d.get("from_addresses") or []
        fps = d.get("fingerprints") or []
        out.append({
            "id": d["id"],
            "from_addrs": set((a or "").lower() for a in fas),
            "fps": [int(x) for x in fps],
            "extract_enabled": bool(d.get("extract_enabled")),
        })
    return out


def try_auto_handle_pg(cur, email: dict):
    """Gate live „Automat": daca emailul se potriveste unui pattern confirmat (acelasi criteriu ca
    regenerarea — expeditor ∈ pattern SI amprenta SimHash Hamming<=PATTERN_MATCH_K), il ataseaza la
    pattern (acumulare identica cu `_run_generation`) si, daca extragerea e activa, il pune in coada.

    psycopg2; NU face commit — tranzactia e a apelantului (process_email.process_one). Pornirea
    thread-ului `_drain_queue` ramane in seama apelantului, DUPA commit. Returneaza
    {"pattern_id", "extract_enabled"} la potrivire, altfel None."""
    patterns = _load_patterns_pg(cur)
    if not patterns:
        return None
    fp = _fp_of(email)
    pid = _match_pattern(email.get("from_address"), fp, patterns)
    if not pid:
        return None
    extract_enabled = any(p["id"] == pid and p["extract_enabled"] for p in patterns)
    eid = email.get("id")
    # Acumulare identica cu _run_generation: append distinct in email_ids, total_matched++, last_seen.
    cur.execute(
        "UPDATE report_patterns SET "
        "email_ids = (SELECT COALESCE(jsonb_agg(DISTINCT x), '[]'::jsonb) "
        "             FROM jsonb_array_elements(email_ids || %s::jsonb) x), "
        "total_matched = total_matched + 1, last_seen_at = now() WHERE id=%s",
        (json.dumps([eid]), pid))
    cur.execute("UPDATE report_patterns SET email_count = jsonb_array_length(email_ids) WHERE id=%s",
                (pid,))
    if extract_enabled:
        cur.execute(
            "INSERT INTO extraction_queue (pattern_id, email_id) VALUES (%s, %s) "
            "ON CONFLICT (pattern_id, email_id) DO NOTHING", (pid, eid))
    return {"pattern_id": pid, "extract_enabled": extract_enabled}


# ── Clustering ──────────────────────────────────────────────────────────────
def _cluster(emails: list) -> list:
    """Grupeaza pe (expeditor + sablon SimHash). Foloseste e['_fp'] precalculat."""
    clusters = []
    by_sender = {}
    for e in emails:
        fa = (e.get("from_address") or "").lower()
        fp = e.get("_fp")
        ns = _WS.sub(" ", re.sub(r"\d+", " ", (e.get("subject") or "").lower())).strip()
        placed = False
        for ci in by_sender.get(fa, []):
            c = clusters[ci]
            if fp is not None and c["rep_fp"] is not None:
                if tfp.hamming(fp, c["rep_fp"]) <= FP_HAMMING_K:
                    c["members"].append(e); placed = True; break
            elif ns and ns == c["norm_subject"]:
                c["members"].append(e); placed = True; break
        if not placed:
            clusters.append({"from_address": fa, "from_name": e.get("from_name") or "",
                             "rep_fp": fp, "norm_subject": ns, "members": [e]})
            by_sender.setdefault(fa, []).append(len(clusters) - 1)
    return clusters


_AI_SYSTEM = (
    "Esti un analist de emailuri. Primesti UN email reprezentativ pentru un GRUP de emailuri "
    "aproape identice (acelasi sablon, primit repetat). Sarcina: stabileste daca este un email "
    "STANDARD generat AUTOMAT de un sistem (alerta, notificare, confirmare, factura/aviz automat, "
    "raport de sistem) — adica genul de email care poate fi procesat IN LOT, nu unul scris de un om.\n"
    "Emailurile pot fi in ORICE limba (frecvent maghiara, engleza, romana). Analizeaza dupa sens.\n\n"
    "Pentru `frequency` propune cat de des ar trebui AGREGAT si trimis un raport pentru acest grup:\n"
    "- once_daily = flux automat constant, un rezumat pe zi e suficient (cazul tipic pentru alerte/notificari);\n"
    "- multiple_daily = volum mare sau urgent, mai multe rapoarte pe zi;\n"
    "- weekly = apare rar;\n"
    "- on_demand = doar daca NU e un flux automat recurent.\n"
    "Pentru `group_label` foloseste o eticheta STABILA si CONSISTENTA pentru acelasi tip de email "
    "(emailuri din acelasi sistem cu acelasi scop trebuie sa primeasca exact aceeasi eticheta).\n\n"
    "Returneaza DOAR un JSON valid, fara text in plus, fara ```, exact in forma:\n"
    '{"is_automated":true|false,'
    '"system_name":"<emitentul/sistemul, ex: HU-GO / Magyar Kozut - Toll>",'
    '"topic":"<subiectul pe scurt, in romana>",'
    '"language":"<cod limba: hu|en|ro|...>",'
    '"suggested_action":"<cum se proceseaza in lot, in romana, o propozitie>",'
    '"frequency":"once_daily|multiple_daily|weekly|on_demand",'
    '"group_label":"<eticheta scurta si stabila a grupului, ex: Alerte toll HU-GO>",'
    '"confidence":<numar 0..1>,'
    '"reason":"<o propozitie scurta in romana>"}'
)

_RETRY_CODES = {"HTTP_502", "HTTP_503", "HTTP_504", "TIMEOUT", "TRANSPORT"}


def _analyze_rep(email: dict) -> dict:
    subj = email.get("subject") or ""
    frm = ((email.get("from_name") or "") + " <" + (email.get("from_address") or "") + ">").strip()
    body = _body_of(email)[:3500]
    content = f"Subiect: {subj}\nDe la: {frm}\n\n{body}".strip()
    res = None
    for attempt in range(3):
        res = iris_ai.run_prompt(
            _AI_SYSTEM, content, response_format="json", temperature=0.0, max_tokens=320,
            task="cargo360:report_grouping", email_id=email.get("id"),
            use_cache=True, learn=True, learn_scope=LEARN_SCOPE)
        if res.get("ok") or (res.get("error") or {}).get("code") not in _RETRY_CODES:
            break
        time.sleep(1.2 * (attempt + 1))
    out = {"is_automated": None, "system_name": None, "topic": None, "language": None,
           "suggested_action": None, "frequency": "on_demand", "group_label": None,
           "confidence": None, "reason": None, "ai_model": res.get("model") if res else None}
    if res and res.get("ok") and isinstance(res.get("parsed"), dict):
        p = res["parsed"]
        out.update({
            "is_automated": bool(p.get("is_automated")),
            "system_name": (p.get("system_name") or None),
            "topic": (p.get("topic") or None),
            "language": (p.get("language") or None),
            "suggested_action": (p.get("suggested_action") or None),
            "frequency": (p.get("frequency") or "on_demand"),
            "group_label": (p.get("group_label") or None),
            "reason": (p.get("reason") or None),
        })
        try:
            out["confidence"] = max(0.0, min(1.0, float(p.get("confidence"))))
        except (TypeError, ValueError):
            out["confidence"] = None
    return out


def _merge_automated(groups: list) -> list:
    """Uneste grupurile is_automated cu aceeasi group_label intr-un singur rand (cumuleaza
    email_ids, from_addresses, fingerprints). Grupurile non-automate raman neatinse."""
    merged = {}
    out = []
    for g in groups:
        lbl = (g.get("group_label") or "").strip().lower()
        if g.get("is_automated") and lbl:
            if lbl in merged:
                m = merged[lbl]
                m["email_ids"] = m["email_ids"] + (g.get("email_ids") or [])
                m["from_addresses"] = m["from_addresses"] + (g.get("from_addresses") or [])
                m["fingerprints"] = m["fingerprints"] + (g.get("fingerprints") or [])
                if (g.get("confidence") or 0) > (m.get("confidence") or 0):
                    for f in ("system_name", "topic", "suggested_action", "frequency",
                              "confidence", "reason", "sample_subject", "sample_email_id",
                              "from_address", "from_name", "group_label"):
                        m[f] = g.get(f)
                continue
            merged[lbl] = g
        out.append(g)
    for m in merged.values():
        m["email_ids"] = list(dict.fromkeys(m["email_ids"]))
        m["from_addresses"] = list(dict.fromkeys(m["from_addresses"]))
        # fingerprints (string) -> int -> dedup near -> string
        ints = _dedup_fps([int(x) for x in m["fingerprints"]])
        m["fingerprints"] = [str(x) for x in ints]
        m["count"] = len(m["email_ids"])
    return out


def _window(since, until, days):
    """Returneaza (conditie SQL pe e.received_at, params, eticheta)."""
    if since:
        cond = "e.received_at >= CAST(CAST(:since AS date) AS timestamptz)"
        params = {"since": since}
        if until:
            cond += " AND e.received_at < CAST((CAST(:until AS date) + 1) AS timestamptz)"
            params["until"] = until
        return cond, params, (since + " … " + (until or "azi"))
    if days:
        return "e.received_at >= now() - (:days || ' days')::interval", {"days": days}, ("ultimele " + str(days) + " zile")
    return "e.received_at >= date_trunc('month', now())", {}, "luna curenta"


def _fetch_emails(db: Session, time_cond: str, params: dict) -> list:
    rows = db.execute(text(
        "SELECT e.id, e.subject, e.from_address, e.from_name, e.received_at, "
        "       e.body_text, e.body_html, e.ai_category "
        "FROM emails e "
        "WHERE " + time_cond + " "
        "  AND COALESCE(NULLIF(btrim(e.body_text),''), NULLIF(btrim(e.body_html),'')) IS NOT NULL "
        "  AND NOT EXISTS (SELECT 1 FROM attachments a WHERE a.email_id = e.id) "
        # Prevenție: bounce-urile NDR NU sunt eligibile pentru învățarea de pattern-uri „automate"
        # (sunt terminale, oprite ca NDR). Oglindește NDR_FROM/SUBJECT_PATTERNS din process_email.
        "  AND COALESCE(e.from_address,'') !~* '(mailer-daemon|postmaster|mail-daemon|bounce)' "
        "  AND COALESCE(e.subject,'') !~* "
        "      '(undeliverable|undelivered|delivery (status notification|failure|failed)|returned mail|non-delivery|nedeliverabil|nelivrat|mesaj returnat)' "
        "ORDER BY e.received_at DESC"), params).fetchall()
    return [dict(r._mapping) for r in rows]


def _run_generation(report_id: int, since, until, days, by: str):
    t0 = time.time()
    db = SessionLocal()
    try:
        cond, params, window = _window(since, until, days)
        emails = _fetch_emails(db, cond, params)
        for e in emails:
            e["_fp"] = _fp_of(e)

        # Excludere: emailurile care se potrivesc unui pattern confirmat nu mai sunt analizate.
        patterns = _load_patterns(db)
        remaining, matched = [], {}
        for e in emails:
            pid = _match_pattern(e.get("from_address"), e.get("_fp"), patterns) if patterns else None
            if pid:
                matched.setdefault(pid, []).append(e["id"])
            else:
                remaining.append(e)
        # acumuleaza emailurile noi in pattern-urile confirmate
        for pid, ids in matched.items():
            db.execute(text(
                "UPDATE report_patterns SET "
                "email_ids = (SELECT COALESCE(jsonb_agg(DISTINCT x), '[]'::jsonb) "
                "             FROM jsonb_array_elements(email_ids || CAST(:new AS jsonb)) x), "
                "total_matched = total_matched + :n, last_seen_at = now() WHERE id=:id"),
                {"new": json.dumps(ids), "n": len(ids), "id": pid})
            db.execute(text("UPDATE report_patterns SET email_count = jsonb_array_length(email_ids) WHERE id=:id"), {"id": pid})
        # auto-enqueue emailurile nou potrivite pt pattern-urile cu extragere activa
        to_drain = []
        for p in patterns:
            if p.get("extract_enabled") and matched.get(p["id"]):
                _enqueue_pattern_emails(db, p["id"], matched[p["id"]])
                to_drain.append(p["id"])
        db.commit()
        for pid in to_drain:
            threading.Thread(target=_drain_queue, args=(pid,), daemon=True).start()

        clusters = _cluster(remaining)
        recurring = [c for c in clusters if len(c["members"]) >= MIN_CLUSTER]
        recurring.sort(key=lambda c: len(c["members"]), reverse=True)
        singletons = len(clusters) - len(recurring)

        prepared = []
        for idx, c in enumerate(recurring):
            members = sorted(c["members"], key=lambda m: (m.get("received_at") or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
            prepared.append((idx, c, members, members[0]))
        to_analyze = prepared[:MAX_AI_CALLS]

        def _work(item):
            return item[0], _analyze_rep(item[3])
        ai_by_idx = {}
        if to_analyze:
            with ThreadPoolExecutor(max_workers=AI_WORKERS) as ex:
                for idx, ai in ex.map(_work, to_analyze):
                    ai_by_idx[idx] = ai
        ai_calls = len(to_analyze)

        groups = []
        for idx, c, members, rep in prepared:
            ai = ai_by_idx.get(idx) or {
                "is_automated": None, "system_name": None, "topic": None, "language": None,
                "suggested_action": "Neanalizat (plafon AI atins) — regenereaza", "frequency": "on_demand",
                "group_label": None, "confidence": None, "reason": None, "ai_model": None}
            ids = [m["id"] for m in members]
            fas = list(dict.fromkeys([(m.get("from_address") or "").lower() for m in members if m.get("from_address")]))
            fps = [str(x) for x in _dedup_fps([m.get("_fp") for m in members])]
            label = ai.get("group_label") or (c["from_name"] or c["from_address"] or "Grup")
            groups.append({
                "group_key": "g%d" % idx,
                "from_address": c["from_address"], "from_name": c["from_name"],
                "from_addresses": fas, "fingerprints": fps,
                "count": len(members), "sample_email_id": rep["id"],
                "sample_subject": rep.get("subject") or "",
                "received_last": (rep.get("received_at").isoformat() if rep.get("received_at") else None),
                "email_ids": ids,
                **{k: ai.get(k) for k in ("is_automated", "system_name", "topic", "language",
                                          "suggested_action", "frequency", "confidence", "reason", "ai_model")},
                "group_label": label,
            })

        groups = _merge_automated(groups)
        groups.sort(key=lambda g: (0 if g.get("is_automated") else 1, -g["count"]))
        automated = [g for g in groups if g.get("is_automated")]
        excluded = sum(len(v) for v in matched.values())

        result = {
            "window": window, "since": since, "until": until,
            "stats": {
                "total_text_noatt": len(emails),
                "excluded_confirmed": excluded,
                "confirmed_patterns": len(patterns),
                "analyzed": len(remaining),
                "clusters": len(clusters),
                "recurring_groups": len(recurring),
                "automated_groups": len(automated),
                "singletons": singletons,
                "ai_calls": ai_calls,
                "covered_by_groups": sum(g["count"] for g in groups),
            },
            "groups": groups,
        }
        dur = int((time.time() - t0) * 1000)
        db.execute(text(
            "UPDATE ai_reports SET status='completed', result=CAST(:r AS jsonb), email_count=:ec, "
            "group_count=:gc, ai_calls=:ai, duration_ms=:d, finished_at=now() WHERE id=:id"),
            {"r": json.dumps(result), "ec": len(emails), "gc": len(groups),
             "ai": ai_calls, "d": dur, "id": report_id})
        db.commit()
        logger.info("report %s done: %d emails (%d excluded), %d groups (%d auto), %d AI, %dms",
                    report_id, len(emails), excluded, len(groups), len(automated), ai_calls, dur)
    except Exception as e:
        logger.exception("report generation failed id=%s", report_id)
        try:
            db.rollback()
            db.execute(text("UPDATE ai_reports SET status='error', error=:e, finished_at=now() WHERE id=:id"),
                       {"e": str(e)[:500], "id": report_id})
            db.commit()
        except Exception:
            pass
    finally:
        db.close()


def _row(r) -> dict:
    d = dict(r._mapping)
    for k in ("generated_at", "finished_at"):
        if d.get(k):
            d[k] = d[k].isoformat()
    return d


@router.post("/reports/email-grouping/generate")
def generate_email_grouping(since: str = Query(None), until: str = Query(None),
                            days: int = Query(None, ge=1, le=120),
                            db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Porneste (in fundal) generarea raportului. since/until = interval de date (YYYY-MM-DD);
    altfel days; altfel luna curenta. UI face poll pe /reports/{id}."""
    if not iris_ai.is_configured():
        raise HTTPException(400, "IRIS AI neconfigurat")
    for d in (since, until):
        if d and not re.match(r"^\d{4}-\d{2}-\d{2}$", d):
            raise HTTPException(400, "Data trebuie sa fie YYYY-MM-DD")
    running = db.execute(text(
        "SELECT id FROM ai_reports WHERE report_type=:t AND status='running' "
        "AND generated_at >= now() - (:s || ' seconds')::interval ORDER BY id DESC LIMIT 1"),
        {"t": REPORT_TYPE, "s": STALE_SECONDS}).fetchone()
    if running:
        return {"ok": True, "already_running": True, "report_id": running[0], "status": "running"}
    by = admin.get("username") or admin.get("email") or "admin"
    rid = db.execute(text(
        "INSERT INTO ai_reports (report_type, status, params, generated_by) "
        "VALUES (:t,'running',CAST(:p AS jsonb),:by) RETURNING id"),
        {"t": REPORT_TYPE, "p": json.dumps({"since": since, "until": until, "days": days}), "by": by}).scalar()
    db.commit()
    threading.Thread(target=_run_generation, args=(rid, since, until, days, by), daemon=True).start()
    return {"ok": True, "started": True, "report_id": rid, "status": "running"}


@router.get("/reports/email-grouping/latest")
def latest_email_grouping(db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    r = db.execute(text("SELECT * FROM ai_reports WHERE report_type=:t ORDER BY id DESC LIMIT 1"),
                   {"t": REPORT_TYPE}).fetchone()
    return {"report": _row(r) if r else None}


@router.get("/reports/{report_id}")
def get_report(report_id: int, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    r = db.execute(text("SELECT * FROM ai_reports WHERE id=:id"), {"id": report_id}).fetchone()
    if not r:
        raise HTTPException(404, "Raport inexistent")
    return {"report": _row(r)}


@router.get("/reports")
def list_reports(limit: int = Query(50, ge=1, le=500),
                 db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    rows = db.execute(text(
        "SELECT id, report_type, status, email_count, group_count, ai_calls, generated_by, "
        "generated_at, duration_ms FROM ai_reports ORDER BY id DESC LIMIT :l"), {"l": limit}).fetchall()
    return {"items": [_row(r) for r in rows]}


@router.post("/reports/patterns/confirm")
def confirm_patterns(body: dict, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Muta grupurile selectate in lista „automate" (report_patterns). La regenerare nu mai sunt
    analizate — emailurile lor sunt atribuite direct pattern-ului. Body: {report_id, group_keys[],
    action?, frequency?}."""
    report_id = body.get("report_id")
    keys = body.get("group_keys") or []
    if not report_id or not isinstance(keys, list) or not keys:
        raise HTTPException(400, "report_id si group_keys (lista nevida) sunt obligatorii")
    r = db.execute(text("SELECT result FROM ai_reports WHERE id=:id"), {"id": report_id}).fetchone()
    if not r or not r[0]:
        raise HTTPException(404, "Raport inexistent sau gol")
    result = r[0] if isinstance(r[0], dict) else json.loads(r[0])
    by_key = {g["group_key"]: g for g in (result.get("groups") or [])}
    by = admin.get("username") or admin.get("email") or "admin"
    created = []
    for k in keys:
        g = by_key.get(k)
        if not g:
            continue
        ids = g.get("email_ids") or []
        pid = db.execute(text(
            "INSERT INTO report_patterns (group_label, system_name, from_addresses, fingerprints, "
            "sample_subject, topic, suggested_action, action, frequency, email_ids, email_count, "
            "total_matched, created_by, last_seen_at) VALUES "
            "(:gl,:sn,CAST(:fa AS jsonb),CAST(:fp AS jsonb),:ss,:tp,:sa,:ac,:fr,CAST(:ids AS jsonb),"
            ":ec,:ec,:by,now()) RETURNING id"),
            {"gl": (g.get("group_label") or "")[:220], "sn": (g.get("system_name") or "")[:220],
             "fa": json.dumps(g.get("from_addresses") or ([g.get("from_address")] if g.get("from_address") else [])),
             "fp": json.dumps(g.get("fingerprints") or []),
             "ss": g.get("sample_subject"), "tp": g.get("topic"), "sa": g.get("suggested_action"),
             "ac": (body.get("action") or "daily_digest")[:64], "fr": body.get("frequency") or g.get("frequency"),
             "ids": json.dumps(ids), "ec": len(ids), "by": by}).scalar()
        created.append({"pattern_id": pid, "group_key": k, "email_count": len(ids)})
    db.commit()
    return {"ok": True, "created": created, "count": len(created)}


@router.get("/reports/patterns/list")
def list_patterns(db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    rows = db.execute(text(
        "SELECT p.id, p.group_label, p.system_name, p.from_addresses, p.sample_subject, p.suggested_action, "
        "p.action, p.frequency, p.email_count, p.total_matched, p.status, p.created_by, p.created_at, "
        "p.last_seen_at, p.extract_enabled, "
        "(SELECT count(*) FROM extracted_records r WHERE r.pattern_id=p.id) AS records, "
        "jsonb_array_length(COALESCE(p.extract_fields,'[]'::jsonb)) AS field_count "
        "FROM report_patterns p WHERE p.status='active' ORDER BY p.total_matched DESC, p.id DESC")).fetchall()
    out = []
    for r in rows:
        d = dict(r._mapping)
        for k in ("created_at", "last_seen_at"):
            if d.get(k):
                d[k] = d[k].isoformat()
        out.append(d)
    return {"items": out}


@router.delete("/reports/patterns/{pattern_id}")
def delete_pattern(pattern_id: int, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Scoate un pattern din lista „automate" (va fi analizat din nou la regenerare)."""
    n = db.execute(text("UPDATE report_patterns SET status='deleted' WHERE id=:id AND status='active'"),
                   {"id": pattern_id}).rowcount
    db.commit()
    if not n:
        raise HTTPException(404, "Pattern inexistent")
    return {"ok": True, "deleted": pattern_id}


# ════════════════════════════════════════════════════════════════════════════
# Extragere de date per-pattern (categorie automată) — prompt AI + coadă + stocare
# ════════════════════════════════════════════════════════════════════════════

def _get_pattern(db: Session, pattern_id: int):
    r = db.execute(text("SELECT * FROM report_patterns WHERE id=:id AND status='active'"),
                   {"id": pattern_id}).fetchone()
    return dict(r._mapping) if r else None


def _sample_email(db: Session, p: dict):
    ids = p.get("email_ids") or []
    if not ids:
        return None
    r = db.execute(text("SELECT id, subject, from_address, from_name, body_text, body_html "
                        "FROM emails WHERE id = ANY(CAST(:ids AS bigint[])) ORDER BY received_at DESC LIMIT 1"),
                   {"ids": ids}).fetchone()
    return dict(r._mapping) if r else None


def _fields_keys(fields):
    return [f.get("name") for f in (fields or []) if f.get("name")]


def _build_extract_system(extract_prompt: str, fields: list) -> str:
    keys = _fields_keys(fields)
    base = (extract_prompt or "").strip()
    tail = ("\n\nReturneaza DOAR un JSON valid, fara text in plus, fara ``` , cu EXACT cheile: "
            + ", ".join(keys) + ". Pentru orice valoare care lipseste in email foloseste null. "
            "Nu inventa valori.")
    return base + tail


def _enqueue_pattern_emails(db: Session, pattern_id: int, email_ids: list) -> int:
    if not email_ids:
        return 0
    db.execute(text(
        "INSERT INTO extraction_queue (pattern_id, email_id) "
        "SELECT :p, (x)::bigint FROM jsonb_array_elements_text(CAST(:ids AS jsonb)) x "
        "ON CONFLICT (pattern_id, email_id) DO NOTHING"),
        {"p": pattern_id, "ids": json.dumps(email_ids)})
    return len(email_ids)


def _extract_one(system: str, email: dict, pattern_id: int):
    """Returneaza (data|None, model|None, err|None)."""
    subj = email.get("subject") or ""
    frm = ((email.get("from_name") or "") + " <" + (email.get("from_address") or "") + ">").strip()
    body = _body_of(email)[:3500]
    content = ("Subiect: " + subj + "\nDe la: " + frm + "\n\n" + body).strip()
    res = None
    for attempt in range(3):
        # IMPORTANT: FARA cache/learn la extragere — fiecare email are date proprii (numar,
        # data, etc.); cache-ul semantic ar returna datele primului email pe emailuri similare.
        res = iris_ai.run_prompt(
            system, content, response_format="json", temperature=0.0, max_tokens=700,
            task="cargo360:extract", email_id=email.get("id"))
        if res.get("ok") or (res.get("error") or {}).get("code") not in _RETRY_CODES:
            break
        time.sleep(1.2 * (attempt + 1))
    if res and res.get("ok") and isinstance(res.get("parsed"), dict):
        return res["parsed"], res.get("model"), None
    err = ((res.get("error") or {}).get("message") if res else "fail") or "raspuns invalid"
    return None, (res.get("model") if res else None), err


def _drain_queue(pattern_id: int):
    """Proceseaza coada pattern-ului: ruleaza promptul de extragere pe fiecare email -> records."""
    db = SessionLocal()
    try:
        p = _get_pattern(db, pattern_id)
        if not p or not p.get("extract_enabled") or not (p.get("extract_prompt") or "").strip():
            return
        system = _build_extract_system(p.get("extract_prompt"), p.get("extract_fields") or [])
        while True:
            rows = db.execute(text(
                "SELECT id, email_id FROM extraction_queue WHERE pattern_id=:p AND status='pending' "
                "ORDER BY id LIMIT 12"), {"p": pattern_id}).fetchall()
            if not rows:
                break
            qids = [r[0] for r in rows]
            db.execute(text("UPDATE extraction_queue SET status='processing', attempts=attempts+1 "
                            "WHERE id = ANY(CAST(:ids AS bigint[]))"), {"ids": qids})
            db.commit()
            emap = {}
            erows = db.execute(text(
                "SELECT id, subject, from_address, from_name, body_text, body_html FROM emails "
                "WHERE id = ANY(CAST(:ids AS bigint[]))"), {"ids": [r[1] for r in rows]}).fetchall()
            for er in erows:
                emap[er[0]] = dict(er._mapping)

            def _work(r):
                em = emap.get(r[1])
                if not em:
                    return (r[0], r[1], None, None, "email lipsa")
                data, model, err = _extract_one(system, em, pattern_id)
                return (r[0], r[1], data, model, err)

            with ThreadPoolExecutor(max_workers=AI_WORKERS) as ex:
                results = list(ex.map(_work, rows))
            for qid, eid, data, model, errm in results:
                if data is not None:
                    db.execute(text(
                        "INSERT INTO extracted_records (pattern_id, email_id, data, model) "
                        "VALUES (:p,:e,CAST(:d AS jsonb),:m) "
                        "ON CONFLICT (pattern_id, email_id) DO UPDATE SET data=EXCLUDED.data, "
                        "model=EXCLUDED.model, extracted_at=now()"),
                        {"p": pattern_id, "e": eid, "d": json.dumps(data), "m": model})
                    db.execute(text("UPDATE extraction_queue SET status='done', processed_at=now(), error=NULL WHERE id=:q"), {"q": qid})
                else:
                    db.execute(text("UPDATE extraction_queue SET status='error', processed_at=now(), error=:e WHERE id=:q"),
                               {"q": qid, "e": (errm or "extras esuat")[:400]})
            db.commit()
        logger.info("drain done pattern=%s", pattern_id)
    except Exception:
        logger.exception("drain queue failed pattern=%s", pattern_id)
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


def _queue_counts(db: Session, pattern_id: int) -> dict:
    rows = db.execute(text("SELECT status, count(*) FROM extraction_queue WHERE pattern_id=:p GROUP BY status"),
                      {"p": pattern_id}).fetchall()
    c = {"pending": 0, "processing": 0, "done": 0, "error": 0}
    for r in rows:
        c[r[0]] = int(r[1])
    c["records"] = int(db.execute(text("SELECT count(*) FROM extracted_records WHERE pattern_id=:p"), {"p": pattern_id}).scalar() or 0)
    return c


_EXTRACT_GEN_SYSTEM = (
    "Esti un asistent care scrie PROMPTURI de extragere de date din emailuri. Primesti: (1) lista "
    "campurilor pe care utilizatorul vrea sa le extraga dintr-un anumit tip de email (cu nume, tip si "
    "descriere), si (2) un email EXEMPLU reprezentativ pentru acel tip. Scrie un prompt CLAR, in romana, "
    "care va fi folosit ca instructiune de sistem pentru un model AI ca sa extraga EXACT acele campuri "
    "din orice email de acest tip. Promptul trebuie: sa explice ce tip de email este, sa listeze campurile "
    "de extras cu unde/cum se gasesc in email, sa ceara returnarea unui JSON cu cheile = numele campurilor, "
    "sa respecte tipul fiecarui camp, si sa puna null cand un camp lipseste. Fa-l GENERAL (nu copia valorile "
    "concrete din exemplu). Returneaza DOAR textul promptului, fara explicatii, fara ``` ."
)


def _fmt_fields(fields: list) -> str:
    out = []
    for f in (fields or []):
        nm = (f.get("name") or "").strip()
        if not nm:
            continue
        out.append("- " + nm + " (tip: " + (f.get("type") or "text") + ")"
                   + ((" — " + f.get("description")) if f.get("description") else ""))
    return "\n".join(out)


@router.get("/reports/patterns/{pattern_id}")
def get_pattern_detail(pattern_id: int, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    p = _get_pattern(db, pattern_id)
    if not p:
        raise HTTPException(404, "Pattern inexistent")
    sample = _sample_email(db, p)
    samp = None
    if sample:
        samp = {"id": sample["id"], "subject": sample.get("subject"),
                "body": _body_of(sample)[:4000], "from_address": sample.get("from_address")}
    return {
        "pattern": {
            "id": p["id"], "group_label": p.get("group_label"), "system_name": p.get("system_name"),
            "from_addresses": p.get("from_addresses") or [], "frequency": p.get("frequency"),
            "email_count": p.get("email_count"), "total_matched": p.get("total_matched"),
            "extract_fields": p.get("extract_fields") or [], "extract_prompt": p.get("extract_prompt"),
            "extract_enabled": bool(p.get("extract_enabled")),
        },
        "sample": samp,
        "queue": _queue_counts(db, pattern_id),
    }


@router.post("/reports/patterns/{pattern_id}/generate-extract-prompt")
def generate_extract_prompt(pattern_id: int, body: dict,
                            db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Genereaza cu AI un prompt de extragere din campurile cerute + un email exemplu."""
    p = _get_pattern(db, pattern_id)
    if not p:
        raise HTTPException(404, "Pattern inexistent")
    fields = body.get("fields") or []
    if not _fields_keys(fields):
        raise HTTPException(400, "Adauga cel putin un camp cu nume")
    sample = _sample_email(db, p)
    sample_txt = ""
    if sample:
        sample_txt = ("Subiect: " + (sample.get("subject") or "") + "\n\n" + _body_of(sample)[:3000])
    extra = (body.get("instructions") or "").strip()
    content = ("CAMPURI DE EXTRAS:\n" + _fmt_fields(fields)
               + (("\n\nINSTRUCTIUNI SUPLIMENTARE:\n" + extra) if extra else "")
               + "\n\nEMAIL EXEMPLU:\n" + (sample_txt or "(indisponibil)"))
    res = iris_ai.run_prompt(_EXTRACT_GEN_SYSTEM, content, response_format="text",
                             temperature=0.2, max_tokens=900, task="cargo360:extract_prompt_gen",
                             email_id=(sample.get("id") if sample else None))
    if not res.get("ok"):
        raise HTTPException(502, detail=res.get("error") or {"code": "FAIL"})
    return {"ok": True, "prompt": (res.get("text") or "").strip()}


@router.post("/reports/patterns/{pattern_id}/test-extract")
def test_extract(pattern_id: int, body: dict,
                 db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Ruleaza promptul (din body sau salvat) pe emailul exemplu si intoarce JSON-ul extras."""
    p = _get_pattern(db, pattern_id)
    if not p:
        raise HTTPException(404, "Pattern inexistent")
    prompt = body.get("prompt") if body.get("prompt") is not None else p.get("extract_prompt")
    fields = body.get("fields") if body.get("fields") is not None else (p.get("extract_fields") or [])
    if not (prompt or "").strip():
        raise HTTPException(400, "Lipseste promptul de extragere")
    sample = _sample_email(db, p)
    if not sample:
        raise HTTPException(400, "Nu exista email exemplu pentru acest pattern")
    system = _build_extract_system(prompt, fields)
    data, model, err = _extract_one(system, sample, pattern_id)
    if data is None:
        raise HTTPException(502, detail={"code": "EXTRACT_FAIL", "message": err})
    return {"ok": True, "data": data, "model": model, "email_id": sample["id"], "subject": sample.get("subject")}


@router.put("/reports/patterns/{pattern_id}/extract")
def save_extract_config(pattern_id: int, body: dict,
                        db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Salveaza campurile + promptul de extragere pe pattern. Daca extract_enabled=true,
    pune in coada toate emailurile pattern-ului si porneste procesarea in fundal."""
    p = _get_pattern(db, pattern_id)
    if not p:
        raise HTTPException(404, "Pattern inexistent")
    fields = body.get("extract_fields")
    prompt = body.get("extract_prompt")
    enabled = bool(body.get("extract_enabled"))
    if enabled and not (prompt or "").strip():
        raise HTTPException(400, "Activarea necesita un prompt de extragere salvat")
    db.execute(text("UPDATE report_patterns SET extract_fields=CAST(:f AS jsonb), extract_prompt=:p, "
                    "extract_enabled=:e WHERE id=:id"),
               {"f": json.dumps(fields if fields is not None else (p.get("extract_fields") or [])),
                "p": prompt if prompt is not None else p.get("extract_prompt"),
                "e": enabled, "id": pattern_id})
    enq = 0
    if enabled:
        enq = _enqueue_pattern_emails(db, pattern_id, p.get("email_ids") or [])
    db.commit()
    if enabled:
        threading.Thread(target=_drain_queue, args=(pattern_id,), daemon=True).start()
    return {"ok": True, "enqueued": enq, "extract_enabled": enabled}


@router.post("/reports/patterns/{pattern_id}/process-queue")
def process_queue(pattern_id: int, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Re-pune in coada emailurile neprocesate si porneste procesarea in fundal."""
    p = _get_pattern(db, pattern_id)
    if not p:
        raise HTTPException(404, "Pattern inexistent")
    if not p.get("extract_enabled") or not (p.get("extract_prompt") or "").strip():
        raise HTTPException(400, "Extragerea nu este activata pe acest pattern")
    enq = _enqueue_pattern_emails(db, pattern_id, p.get("email_ids") or [])
    db.commit()
    threading.Thread(target=_drain_queue, args=(pattern_id,), daemon=True).start()
    return {"ok": True, "enqueued": enq, "queue": _queue_counts(db, pattern_id)}


@router.get("/reports/patterns/{pattern_id}/queue-status")
def queue_status(pattern_id: int, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    return {"ok": True, "queue": _queue_counts(db, pattern_id)}


@router.get("/reports/patterns/{pattern_id}/records")
def pattern_records(pattern_id: int, limit: int = Query(100, ge=1, le=1000),
                    db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Datele extrase (sursa pt endpoint-ul de expunere viitor)."""
    rows = db.execute(text(
        "SELECT email_id, data, model, extracted_at FROM extracted_records WHERE pattern_id=:p "
        "ORDER BY extracted_at DESC LIMIT :l"), {"p": pattern_id, "l": limit}).fetchall()
    out = []
    for r in rows:
        d = dict(r._mapping)
        if d.get("extracted_at"):
            d["extracted_at"] = d["extracted_at"].isoformat()
        out.append(d)
    return {"items": out, "count": len(out)}


@router.get("/reports/extraction/overview")
def extraction_overview(db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Privire de ansamblu pentru coada de EXTRAGERE — separata de celelalte procesari AI,
    cu cost propriu (din ai_call_log task='extract')."""
    q = dict(db.execute(text(
        "SELECT count(*) FILTER (WHERE status='pending') AS pending, "
        "count(*) FILTER (WHERE status='processing') AS processing, "
        "count(*) FILTER (WHERE status='done') AS done, "
        "count(*) FILTER (WHERE status='error') AS error, count(*) AS total FROM extraction_queue"
    )).fetchone()._mapping)
    records = int(db.execute(text("SELECT count(*) FROM extracted_records")).scalar() or 0)
    per = db.execute(text(
        "SELECT p.id, p.group_label, p.extract_enabled, "
        "count(eq.id) FILTER (WHERE eq.status='pending') AS pending, "
        "count(eq.id) FILTER (WHERE eq.status='done') AS done, "
        "count(eq.id) FILTER (WHERE eq.status='error') AS error, "
        "(SELECT count(*) FROM extracted_records r WHERE r.pattern_id=p.id) AS records "
        "FROM report_patterns p LEFT JOIN extraction_queue eq ON eq.pattern_id=p.id "
        "WHERE p.status='active' GROUP BY p.id, p.group_label, p.extract_enabled "
        "ORDER BY records DESC, p.id DESC")).fetchall()

    def _cost(task):
        m = db.execute(text(
            "SELECT count(*) AS calls, COALESCE(sum(cost_usd),0) AS cost, "
            "COALESCE(sum(tokens_in),0) AS tin, COALESCE(sum(tokens_out),0) AS tout, "
            "count(*) FILTER (WHERE NOT ok) AS errors FROM ai_call_log WHERE task IN (:t, :tp)"),
            {"t": task, "tp": "cargo360:" + task}).fetchone()._mapping
        td = db.execute(text(
            "SELECT count(*) AS calls, COALESCE(sum(cost_usd),0) AS cost FROM ai_call_log "
            "WHERE task IN (:t, :tp) AND created_at >= CURRENT_DATE"), {"t": task, "tp": "cargo360:" + task}).fetchone()._mapping
        return {"calls": m["calls"] or 0, "cost": float(m["cost"] or 0),
                "tokens_in": int(m["tin"] or 0), "tokens_out": int(m["tout"] or 0),
                "errors": m["errors"] or 0, "today_calls": td["calls"] or 0,
                "today_cost": float(td["cost"] or 0)}

    return {
        "queue": {"pending": q["pending"], "processing": q["processing"], "done": q["done"],
                  "error": q["error"], "total": q["total"], "records": records},
        "per_pattern": [{
            "id": r._mapping["id"], "group_label": r._mapping["group_label"],
            "extract_enabled": bool(r._mapping["extract_enabled"]),
            "pending": int(r._mapping["pending"] or 0), "done": int(r._mapping["done"] or 0),
            "error": int(r._mapping["error"] or 0), "records": int(r._mapping["records"] or 0),
        } for r in per],
        "cost": _cost("extract"),
        "cost_prompt_gen": _cost("extract_prompt_gen"),
    }


@router.post("/reports/patterns/{pattern_id}/reprocess")
def reprocess_queue(pattern_id: int, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Reprocesează TOATE emailurile categoriei (inclusiv cele deja extrase) — resetează coada
    la pending și re-rulează promptul curent. Util după ce ai modificat promptul/câmpurile.
    Datele extrase se suprascriu (upsert)."""
    p = _get_pattern(db, pattern_id)
    if not p:
        raise HTTPException(404, "Pattern inexistent")
    if not p.get("extract_enabled") or not (p.get("extract_prompt") or "").strip():
        raise HTTPException(400, "Extragerea nu este activată pe acest pattern")
    enq = _enqueue_pattern_emails(db, pattern_id, p.get("email_ids") or [])
    db.execute(text("UPDATE extraction_queue SET status='pending', error=NULL, processed_at=NULL "
                    "WHERE pattern_id=:p"), {"p": pattern_id})
    db.commit()
    threading.Thread(target=_drain_queue, args=(pattern_id,), daemon=True).start()
    return {"ok": True, "reprocessing": True, "queue": _queue_counts(db, pattern_id)}


# --------------------------------------------------------------------------- #
# Raport zilnic Undeliverable (NDR) -> CTS
# --------------------------------------------------------------------------- #
def _ndr_resolve_date(date):
    from datetime import date as _date
    if date:
        try:
            return _date.fromisoformat(date)
        except ValueError:
            raise HTTPException(400, "Parametru 'date' invalid (format YYYY-MM-DD)")
    db2 = SessionLocal()
    try:
        return db2.execute(text(
            "SELECT ((now() AT TIME ZONE 'Europe/Bucharest')::date - 1)")).scalar()
    finally:
        db2.close()


@router.post("/reports/ndr-daily/run-now")
def ndr_daily_run_now(date: str = Query(None, description="YYYY-MM-DD; default = ieri"),
                      force: bool = Query(False, description="regenereaza daca exista deja"),
                      admin=Depends(get_current_admin)):
    """Genereaza ACUM raportul Undeliverable pentru o zi (default ieri) si il
    injecteaza in feed-ul CTS ca email sintetic auto_report. Ignora gate-ul de
    ora/last_report (pentru test la cerere)."""
    from app.services import ndr_report
    return ndr_report.generate_for_date(_ndr_resolve_date(date), force=force)


@router.get("/reports/ndr-daily/preview")
def ndr_daily_preview(date: str = Query(None, description="YYYY-MM-DD; default = ieri"),
                      admin=Depends(get_current_admin)):
    """Previzualizare (fara injectare): randurile + HTML-ul raportului pentru o zi."""
    from app.services import ndr_report
    return ndr_report.preview_for_date(_ndr_resolve_date(date))
