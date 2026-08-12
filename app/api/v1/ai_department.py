"""Incadrare email pe DEPARTAMENT — stats, reclasificare per-email, corectii (learning).

Emailurile noi primesc departament automat in pipeline (process_email). Aceste endpoint-uri
permit reclasificarea unui email dupa editarea regulilor/prompturilor si gestionarea corectiilor
manuale (fine-tuning). Mirror al ai_category.py.

IMPORTANT: corectia de departament NU atinge manual_review_state/result — aceea e detinuta de
clasificarea pe categorie (esantionul zilnic de QA).
"""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import get_db
from app.api.v1.auth import get_current_admin
from app.services import department_classifier as D
from app.services import iris_ai

logger = logging.getLogger("mailguard.ai_department")
router = APIRouter()


def _classify_and_store(db: Session, email_id: int, force_fresh: bool = False) -> dict:
    row = db.execute(text(
        "SELECT id, subject, from_address, from_name, body_text, body_html "
        "FROM emails WHERE id=:id"), {"id": email_id}).fetchone()
    if not row:
        raise HTTPException(404, "Email not found")
    res = D.classify_department(dict(row._mapping), force_fresh=force_fresh)
    db.execute(text(
        "UPDATE emails SET ai_department=:d, ai_department_result=CAST(:r AS jsonb), "
        "ai_department_at=NOW() WHERE id=:id"),
        {"d": res["department"], "r": json.dumps(res), "id": email_id})
    db.commit()
    return res


@router.post("/ai/department/{email_id}/run")
def department_run_one(email_id: int, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """(Re)incadreaza pe departament un singur email — ocoleste curated-cache (force_fresh=True).

    Pas 0: daca ai_op_series e gol, ruleaza extractor inainte de bypass — prinde emailurile
    sosite inainte ca worker-ul periodic sa fi rulat.
    Daca serie gasita → departament determinat din prefix (PPBG/PPCB/PPHU/ASCF → suport_1).
    """
    # Pas 0: extrage seria OP și moneda dacă lipsesc; persistă și decide departamentul
    pre = db.execute(text("SELECT ai_op_series FROM emails WHERE id=:id"),
                     {"id": email_id}).fetchone()
    if pre and not pre._mapping.get("ai_op_series"):
        try:
            from app.services import op_extractor
            op_result = op_extractor.extract_op_series(email_id)
            series = op_result.get("series")
            currency = op_result.get("currency")
            dept_op = op_result.get("department")

            if currency == "MDL":
                # MDL → contabilitate imediat, indiferent de serie
                db.execute(text(
                    "UPDATE emails SET ai_op_series=:s, ai_op_extract_at=NOW() WHERE id=:id"),
                    {"s": series, "id": email_id})
                res = {"department": "contabilitate", "confidence": 1.0, "model": "op_mdl",
                       "reason": "Moneda MDL detectata in OP — rutare automata la contabilitate.",
                       "op_series": series, "currency": "MDL"}
                db.execute(text(
                    "UPDATE emails SET ai_department=:d, ai_department_result=CAST(:r AS jsonb), "
                    "ai_department_at=NOW() WHERE id=:id"),
                    {"d": "contabilitate", "r": json.dumps(res), "id": email_id})
                db.commit()
                return {"ok": True, "email_id": email_id, "ai_department": "contabilitate",
                        "ai_department_result": res}

            if series:
                db.execute(text(
                    "UPDATE emails SET ai_op_series=:s, ai_op_extract_at=NOW() WHERE id=:id"),
                    {"s": series, "id": email_id})
                db.commit()
        except Exception:
            logger.exception("department_run_one: op_extractor failed for email_id=%s", email_id)

    op_row = db.execute(text("SELECT ai_op_series FROM emails WHERE id=:id"),
                        {"id": email_id}).fetchone()
    if op_row and op_row._mapping.get("ai_op_series"):
        from app.services.op_extractor import _department_from_series
        series = op_row._mapping["ai_op_series"]
        dept = _department_from_series(series)

        # CargoFuel override: expeditor @cargotrack.ro sau subiect [CargoFuel] → suport_1 mereu,
        # indiferent de seria detectată (seria poate fi fals pozitiv din CUI/cod firmă).
        email_meta = db.execute(text(
            "SELECT from_address, subject FROM emails WHERE id=:id"), {"id": email_id}).fetchone()
        if email_meta:
            _from = (email_meta._mapping.get("from_address") or "").lower()
            _subj = (email_meta._mapping.get("subject") or "").lower()
            if "@cargotrack.ro" in _from or "cargofuel" in _subj:
                dept = "suport_1"

        res = {"department": dept, "confidence": 1.0, "model": "op_series",
               "reason": f"Serie OP {series} detectata — departament determinat din prefix serie.",
               "op_series": series}
        db.execute(text(
            "UPDATE emails SET ai_department=:d, ai_department_result=CAST(:r AS jsonb), "
            "ai_department_at=NOW() WHERE id=:id"),
            {"d": dept, "r": json.dumps(res), "id": email_id})
        db.commit()
        return {"ok": True, "email_id": email_id, "ai_department": dept, "ai_department_result": res}

    res = _classify_and_store(db, email_id, force_fresh=True)
    return {"ok": True, "email_id": email_id, "ai_department": res["department"], "ai_department_result": res}


@router.post("/ai/department/{email_id}/correct")
def department_correct(email_id: int, body: dict, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Corecteaza manual departamentul unui email. Alimenteaza fine-tuning-ul (ai_department_corrections).
    NU atinge manual_review_state (acela e al categoriei)."""
    new_dep = (body.get("department") or "").strip().lower()
    if new_dep not in D.DEPARTMENTS:
        raise HTTPException(400, "Departament invalid")
    row = db.execute(text("SELECT ai_department, ai_department_result FROM emails WHERE id=:id"),
                     {"id": email_id}).fetchone()
    if not row:
        raise HTTPException(404, "Email not found")
    old_dep = row._mapping["ai_department"]
    old_reason = None
    try:
        old_reason = (row._mapping["ai_department_result"] or {}).get("reason")
    except Exception:
        pass
    reviewer = admin.get("username") or admin.get("email") or "admin"
    db.execute(text(
        "INSERT INTO ai_department_corrections(email_id, old_department, new_department, old_reason, corrected_by) "
        "VALUES(:e, :o, :n, :r, :by)"),
        {"e": email_id, "o": old_dep, "n": new_dep, "r": old_reason, "by": reviewer})
    new_result = {"department": new_dep, "confidence": 1.0,
                  "reason": "Corectat manual de " + reviewer, "model": "manual", "manual": True}
    db.execute(text(
        "UPDATE emails SET ai_department=:d, ai_department_result=CAST(:r AS jsonb), "
        "ai_department_manual=TRUE, ai_department_at=NOW() WHERE id=:id"),
        {"d": new_dep, "r": json.dumps(new_result), "id": email_id})
    db.commit()
    return {"ok": True, "email_id": email_id, "old_department": old_dep,
            "new_department": new_dep, "ai_department_result": new_result}


@router.get("/ai/department/corrections")
def department_corrections(limit: int = Query(200, ge=1, le=2000),
                           db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Lista emailurilor incadrate gresit pe departament (corectii manuale): vechi vs nou.
    Exclude Suport 1 din ambele parti — e departamentul fallback, nu un verdict real de training."""
    rows = db.execute(text(
        "SELECT c.id, c.email_id, c.old_department, c.new_department, c.old_reason, c.corrected_by, "
        "to_char(c.created_at,'YYYY-MM-DD HH24:MI') AS created_at, "
        "e.subject, e.from_address, e.ai_department AS current_department "
        "FROM ai_department_corrections c JOIN emails e ON e.id=c.email_id "
        "WHERE c.old_department <> 'suport_1' AND c.new_department <> 'suport_1' "
        "ORDER BY c.id DESC LIMIT :l"), {"l": limit}).fetchall()
    total = db.execute(text(
        "SELECT count(*) FROM ai_department_corrections "
        "WHERE old_department <> 'suport_1' AND new_department <> 'suport_1'")).scalar()
    return {"total": total, "items": [dict(r._mapping) for r in rows]}


@router.delete("/ai/department/corrections")
def department_corrections_reset(db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Reset: sterge TOATE corectiile de departament. NU atinge prompturile/regulile. Ireversibil."""
    n = db.execute(text("SELECT count(*) FROM ai_department_corrections")).scalar() or 0
    db.execute(text("DELETE FROM ai_department_corrections"))
    db.commit()
    return {"ok": True, "deleted": int(n)}


@router.get("/ai/department/stats")
def department_stats(db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    by_dep = db.execute(text(
        "SELECT COALESCE(ai_department,'(neincadrat)') AS department, count(*) AS n "
        "FROM emails GROUP BY ai_department ORDER BY n DESC")).fetchall()
    return {
        "configured": iris_ai.is_configured(),
        "labels": D.DEPT_LABELS,
        "by_department": [dict(r._mapping) for r in by_dep],
    }


def _regen_system() -> str:
    keys = ",".join('"' + s + '":"<reguli complete>"' for s in D.EDITABLE)
    labels = "; ".join(s + "=" + D.DEPT_LABELS[s] for s in D.EDITABLE)
    return (
        "Esti expert in prompt engineering pentru un sistem care incadreaza emailuri de suport in 8 "
        "departamente (" + labels + ") pe baza unor reguli text per departament. Primesti regulile "
        "actuale si o lista de emailuri pe care sistemul le-a incadrat GRESIT (departamentul dat de AI "
        "vs cel corect dat de om). Imbunatateste regulile astfel incat aceste emailuri sa fie incadrate "
        "CORECT pe viitor, pastrand reguli GENERALE si clare (NU hardcoda emailuri specifice). Pastreaza "
        "ce e bun; ajusteaza/adauga doar ce e necesar. Returneaza DOAR JSON valid, fara ```, cu forma "
        "exacta: {" + keys + ',"explicatie":"<ce ai schimbat, scurt, in romana>"}'
    )


def _regen_system_one(dep: str) -> str:
    """System prompt pentru regenerarea promptului UNUI singur departament."""
    return (
        "Esti expert in prompt engineering pentru un sistem care incadreaza emailuri de suport pe "
        "departamente, pe baza unor reguli text per departament. Lucrezi pe UN SINGUR departament: "
        + D.DEPT_LABELS[dep] + " (" + dep + "). Primesti promptul ACTUAL al acestui departament si "
        "exemple de emailuri incadrate GRESIT care implica acest departament: (A) emailuri pe care "
        "AI le-a pus aici desi NU apartin (promptul e prea larg) si (B) emailuri care AR FI TREBUIT "
        "puse aici dar au mers altundeva (promptul e prea ingust). RESCRIE COMPLET promptul ACESTUI "
        "departament astfel incat aceste cazuri sa fie incadrate CORECT pe viitor: clarifica ce "
        "APARTINE si ce NU apartine departamentului, pastrand reguli GENERALE si clare (NU hardcoda "
        "adrese/subiecte specifice). NU adauga pur si simplu reguli noi peste cele vechi: ELIMINA "
        "redundantele, repetitiile, regulile contradictorii sau invechite, comaseaza ce spune acelasi "
        "lucru si rescrie totul coerent de la zero. Rezultatul trebuie sa fie mai clar si (de regula) "
        "mai scurt decat intrarea, nu mai lung. "
        "IMPORTANT pentru format: raspunsul tau INCEPE direct cu caracterul { si SE TERMINA cu }. "
        "NU scrie NICIUN text, analiza sau explicatie inainte de JSON. NU folosi blocuri markdown (```), "
        "NU enumera cazurile. Toata explicatia (MAX 2 propozitii) o pui in campul \"explicatie\". "
        "Returneaza EXCLUSIV un obiect JSON valid, cu forma exacta: "
        '{"prompt":"<reguli complete imbunatatite>","explicatie":"<ce ai schimbat, scurt, in romana>"}'
    )


def _salvage_prompt_json(raw):
    """Recupereaza {prompt, explicatie} dintr-un raspuns AI care NU e JSON pur: proza + bloc
    ```json, JSON cu text in jur, sau JSON TRUNCHIAT (modelul a depasit max_tokens). Returneaza
    dict valid sau None. Plasa de siguranta pentru cand modelul ignora instructiunea de format."""
    import re
    if not raw or not isinstance(raw, str):
        return None
    cands = []
    # 1) blocuri fenced ```json ... ``` (sau ``` ... ```)
    for m in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL):
        cands.append(m.group(1))
    # 2) primul obiect { ... } balansat din tot textul
    st = raw.find("{")
    if st != -1:
        depth = 0
        for i in range(st, len(raw)):
            c = raw[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    cands.append(raw[st:i + 1])
                    break
    for cand in cands:
        try:
            obj = json.loads(cand)
        except Exception:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("prompt"), str) and obj["prompt"].strip():
            return obj
    # 3) TRUNCHIAT: extrage valoarea "prompt" chiar dak JSON-ul nu se inchide
    m = re.search(r'"prompt"\s*:\s*"', raw)
    if m:
        rest = raw[m.end():]
        out = []
        i = 0
        esc = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "/": "/"}
        while i < len(rest):
            c = rest[i]
            if c == "\\" and i + 1 < len(rest):
                out.append(esc.get(rest[i + 1], rest[i + 1]))
                i += 2
                continue
            if c == '"':
                break
            out.append(c)
            i += 1
        val = "".join(out).strip()
        if val:
            return {"prompt": val, "explicatie": "(recuperat dintr-un raspuns AI trunchiat)"}
    return None


def _regen_system_text(dep: str) -> str:
    """A doua incercare: cerem promptul ca TEXT PUR (fara JSON), pentru departamentele unde modelul
    raspunde verbos si JSON-ul se trunchiaza. Eliminam complet riscul de parsare."""
    return (
        "Esti expert in prompt engineering pentru un sistem care incadreaza emailuri pe departamente. "
        "Rescrie COMPLET si consolideaza promptul de incadrare pentru departamentul "
        + D.DEPT_LABELS[dep] + " (" + dep + "), pe baza promptului actual si a exemplelor de emailuri "
        "incadrate gresit. Clarifica ce APARTINE si ce NU apartine, pastrand reguli GENERALE (nu "
        "hardcoda adrese/subiecte). NU adauga reguli noi peste cele vechi: elimina redundantele si "
        "repetitiile, comaseaza ce spune acelasi lucru, rescrie coerent de la zero; rezultatul trebuie "
        "sa fie mai clar si (de regula) mai scurt, nu mai lung. "
        "FORMAT OBLIGATORIU: returnezi DOAR textul noului prompt, in romana. "
        "Fara JSON, fara ```, fara explicatii, fara introducere de tipul \"Iata promptul\". "
        "Raspunsul tau INCEPE direct cu prima regula a promptului."
    )


@router.post("/ai/department/regenerate-prompts")
def regenerate_prompts(body: dict = None, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Regenereaza promptul UNUI singur departament (param 'department'), pe baza corectiilor care
    implica acel departament. Per-departament (NU toate odata) ca sa evite truncarea la tokeni si
    timeout-ul gunicorn (60s) - UI-ul itereaza prin departamente. NU salveaza automat."""
    if not iris_ai.is_configured():
        raise HTTPException(400, "IRIS AI neconfigurat")
    body = body or {}
    use_cts = bool(body.get("use_cts"))
    dep = (body.get("department") or "").strip().lower()
    # Model implicit: sonnet (calitate > cost la rescrierea prompturilor). Override: body['model'].
    # claude-sonnet-5 respins de gateway IRIS (temperature deprecated); claude-sonnet-4-5 e echivalent si stabil.
    _model = (body.get("model") or "claude-sonnet-4-5").strip()
    if not dep:
        raise HTTPException(400, "Specifica 'department' - regenerarea se face per departament.")
    if dep not in D.EDITABLE:
        raise HTTPException(400, "Departament invalid")
    prompts = D.load_prompts()
    if use_cts:
        # Adevar de teren CTS: AI a pus ai_department, suportul a setat in CTS cts_department (diferit),
        # pe mailuri PRIMITE. Acelasi format old/new ca la corectiile manuale.
        rows = db.execute(text(
            "SELECT e.ai_department AS old_department, gt.cts_department AS new_department, "
            "       e.subject, LEFT(COALESCE(e.body_text, e.body_html, ''), 300) AS snippet "
            "FROM cts_ground_truth gt JOIN emails e ON e.id=gt.email_id "
            "WHERE COALESCE(gt.cts_direction,'received')='received' "
            "  AND gt.cts_department IS NOT NULL AND e.ai_department IS NOT NULL "
            "  AND gt.cts_department <> e.ai_department "
            "  AND (e.ai_department=:d OR gt.cts_department=:d) "
            "ORDER BY gt.changed_at DESC NULLS LAST, gt.id DESC LIMIT 200"), {"d": dep}).fetchall()
    else:
        # Deduplicam la ULTIMA corectie per email (verdictul final al omului), excludem no-op-urile,
        # apoi pastram doar corectiile care implica ACEST departament (ca old SAU ca new).
        rows = db.execute(text(
            "SELECT old_department, new_department, subject, snippet FROM ("
            "  SELECT DISTINCT ON (c.email_id) c.email_id, c.id, c.old_department, c.new_department, "
            "         e.subject, LEFT(COALESCE(e.body_text, e.body_html, ''), 300) AS snippet "
            "  FROM ai_department_corrections c JOIN emails e ON e.id=c.email_id "
            "  ORDER BY c.email_id, c.id DESC"
            ") latest "
            "WHERE old_department IS DISTINCT FROM new_department "
            "  AND (old_department=:d OR new_department=:d) "
            "ORDER BY id DESC LIMIT 200"), {"d": dep}).fetchall()
    corr = [r._mapping for r in rows]
    fp = [m for m in corr if m["old_department"] == dep]   # AI a pus GRESIT aici (corect e altul)
    fn = [m for m in corr if m["new_department"] == dep]   # ar fi trebuit aici (AI a pus altundeva)
    if not fp and not fn:
        # Departamentul apare doar in corectii suprascrise/email sters => niciun semnal valid.
        # Nu e o eroare: il raportam ca SARIT ca UI-ul sa nu il afiseze ca esec.
        return {"ok": True, "department": dep, "skipped": True, "reason": "no_corrections",
                "suggested": {}, "based_on": 0, "fp": 0, "fn": 0}
    lines = ["DEPARTAMENT TINTA: " + D.DEPT_LABELS[dep] + " (" + dep + ")",
             "\nPROMPT ACTUAL:\n" + (prompts.get(dep) or "")]
    if fp:
        lines.append("\n\n[A] Emailuri pe care AI le-a pus GRESIT in acest departament (de fapt "
                     "apartin altui departament) - promptul e PREA LARG, clarifica ce NU apartine:")
        for i, m in enumerate(fp, 1):
            lines.append("\n(" + str(i) + ") Corect era: " + str(m["new_department"]) +
                         " | Subiect: " + (m["subject"] or "(gol)") +
                         "\n    Continut: " + (m["snippet"] or "").strip())
    if fn:
        lines.append("\n\n[B] Emailuri care AR FI TREBUIT puse in acest departament dar AI le-a pus "
                     "altundeva - promptul e PREA INGUST, adauga indiciile lipsa:")
        for i, m in enumerate(fn, 1):
            lines.append("\n(" + str(i) + ") AI a pus gresit in: " + str(m["old_department"]) +
                         " | Subiect: " + (m["subject"] or "(gol)") +
                         "\n    Continut: " + (m["snippet"] or "").strip())
    content = "\n".join(lines)
    res = iris_ai.run_prompt(_regen_system_one(dep), content, response_format="json",
                             model_hint=_model,
                             max_tokens=4500, task="cargo360:dept_prompt_regen", no_cache=True)
    parsed = res.get("parsed") or {}
    v = parsed.get("prompt") if isinstance(parsed, dict) else None
    if not (isinstance(v, str) and v.strip()):
        # Modelul a raspuns cu proza + ```json (in loc de JSON pur) sau gateway-ul nu a putut parsa
        # (JSON_PARSE_ERROR), eventual cu raspuns trunchiat. Incercam sa recuperam din textul brut.
        err = res.get("error") if isinstance(res.get("error"), dict) else {}
        raw = res.get("text") or err.get("raw_text") or ""
        salv = _salvage_prompt_json(raw)
        if salv:
            parsed = salv
            v = parsed.get("prompt")
    if not (isinstance(v, str) and v.strip()):
        # Ultima plasa: a doua incercare cerand promptul ca TEXT PUR (fara JSON). Asa departamentele
        # cu raspuns lung/verbos (ex. suport_2 pe instante cu multe corectii) nu mai pica pe trunchiere.
        res2 = iris_ai.run_prompt(_regen_system_text(dep), content, response_format="text",
                                  model_hint=_model,
                                  max_tokens=4000, task="cargo360:dept_prompt_regen", no_cache=True)
        t2 = (res2.get("text") or "").strip()
        if t2.startswith("```"):
            import re as _re2
            t2 = _re2.sub(r"^```[a-zA-Z]*\s*", "", t2)
            t2 = _re2.sub(r"\s*```\s*$", "", t2).strip()
        # Modelul poate raspunde tot ca JSON chiar si in modul text -> extragem prompt-ul din el.
        # Daca nu e JSON (text pur), il folosim ca atare.
        salv2 = _salvage_prompt_json(t2) if t2 else None
        if salv2 and isinstance(salv2.get("prompt"), str) and salv2["prompt"].strip():
            parsed = {"prompt": salv2["prompt"].strip(), "explicatie": "(regenerat in mod text)"}
            v = parsed["prompt"]
        elif t2 and not t2.lstrip().startswith("{"):
            parsed = {"prompt": t2, "explicatie": "(regenerat in mod text)"}
            v = t2
    if not (isinstance(v, str) and v.strip()):
        if not res.get("ok"):
            raise HTTPException(502, "Regenerare esuata: " + str(res.get("error")))
        raise HTTPException(502, "AI nu a returnat un prompt valid")
    return {"ok": True, "department": dep, "suggested": {dep: v.strip()},
            "explicatie": parsed.get("explicatie"), "based_on": len(corr),
            "source": ("cts" if use_cts else "manual"),
            "fp": len(fp), "fn": len(fn), "model": res.get("model"), "usage": res.get("usage")}


# ---------------------------------------------------------------------------
# Reincadrare DEPARTAMENT in FUNDAL (server-side, fire-and-forget) — mirror al categoriei.
# Departamentul nu are coloana 'pending', deci folosim un marker temporal (job_start):
# scriptul proceseaza emailurile cu ai_department_at IS NULL SAU < job_start si seteaza
# ai_department_at=NOW() pe masura ce avanseaza => reluare automata. Sare corectiile manuale.
# ---------------------------------------------------------------------------
import os
import subprocess
import signal as _signal
from datetime import datetime, timezone

_APP_DIR = "/opt/iris-mailguard"
_DEPT_STATUS_FILE = f"{_APP_DIR}/logs/reclassify_dept_status.json"
_PY = f"{_APP_DIR}/venv/bin/python"
_DEPT_STALE_SECONDS = 180


def _read_dept_status():
    try:
        with open(_DEPT_STATUS_FILE) as f:
            return json.load(f)
    except Exception:
        return None


def _dept_is_alive(st) -> bool:
    if not st or not st.get("running"):
        return False
    try:
        ts = datetime.fromisoformat(st["updated_at"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds() < _DEPT_STALE_SECONDS
    except Exception:
        return False


def _dept_pending_count(db, st):
    """Cate emailuri mai raman de reincadrat pentru jobul curent (acelasi marker ca scriptul)."""
    js = (st or {}).get("job_start")
    if not js:
        return None
    conds = ["status <> 'ndr'", "(ai_department_manual IS NOT TRUE)",
             "(ai_department_at IS NULL OR ai_department_at < :js)"]
    params = {"js": js}
    sc = (st or {}).get("scope") or "all"
    if sc.startswith("date:"):
        conds.append("received_at >= :fd"); params["fd"] = sc[5:]
    elif sc.startswith("id:"):
        conds.append("id >= :fid"); params["fid"] = int(sc[3:])
    q = "SELECT count(*) FROM emails WHERE " + " AND ".join(conds)
    return int(db.execute(text(q), params).scalar() or 0)


@router.post("/ai/department/reclassify/start")
def dept_reclassify_start(from_date: str = Query(None), from_id: int = Query(None),
                          fresh: bool = Query(True),
                          db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Porneste reincadrarea pe DEPARTAMENT in fundal (toate / de la data / de la id), cu
    prompturile+regulile curente. Sare emailurile corectate manual. Continua daca inchizi UI-ul.
    Dublu-click => intoarce jobul existent (nu dubleaza costul AI).
    fresh=True (implicit) ocoleste curated-cache ca prompturile curente sa se aplice efectiv."""
    cur = _read_dept_status()
    if _dept_is_alive(cur):
        return {"ok": True, "already_running": True, "status": cur}

    job_start = datetime.now(timezone.utc).isoformat()
    conds = ["status <> 'ndr'", "(ai_department_manual IS NOT TRUE)",
             "(ai_department_at IS NULL OR ai_department_at < :js)"]
    params = {"js": job_start}
    args = [_PY, "-m", "scripts.reclassify_dept_all", "--job-start", job_start]
    if fresh:
        args.append("--fresh")
    if from_date:
        conds.append("received_at >= :fd"); params["fd"] = from_date
        args += ["--from-date", from_date]
    if from_id is not None:
        conds.append("id >= :fid"); params["fid"] = from_id
        args += ["--from-id", str(from_id)]

    total = db.execute(text("SELECT count(*) FROM emails WHERE " + " AND ".join(conds)), params).scalar()

    subprocess.Popen(args, cwd=_APP_DIR, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
    logger.info("dept reclassify background started: %s (total=%s)", args, total)
    return {"ok": True, "started": True, "total": int(total or 0),
            "scope": from_date or (("id:" + str(from_id)) if from_id is not None else "all")}


@router.post("/ai/department/reclassify/cancel")
def dept_reclassify_cancel(admin=Depends(get_current_admin)):
    """Opreste jobul de reincadrare pe departament. Emailurile deja procesate raman; restul pot fi
    reluate cu Porneste."""
    st = _read_dept_status()
    if not st or not st.get("running"):
        return {"ok": True, "was_running": False, "note": "Niciun job activ."}
    pid = st.get("pid")
    killed = False
    if pid:
        try:
            os.kill(int(pid), _signal.SIGTERM)
            killed = True
        except ProcessLookupError:
            pass
        except Exception as e:
            logger.warning("dept cancel kill failed pid=%s: %s", pid, e)
    st["running"] = False
    st["canceled"] = True
    try:
        tmp = _DEPT_STATUS_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(st, f)
        os.replace(tmp, _DEPT_STATUS_FILE)
    except Exception:
        pass
    logger.info("dept reclassify canceled pid=%s killed=%s", pid, killed)
    return {"ok": True, "was_running": True, "killed": killed, "processed": st.get("processed", 0)}


@router.get("/ai/department/reclassify/status")
def dept_reclassify_status(db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Progresul jobului de reincadrare pe departament. running=true cat timp mai sunt emailuri."""
    st = _read_dept_status()
    alive = _dept_is_alive(st)
    out = {"alive": alive, "pending_now": _dept_pending_count(db, st)}
    if st:
        out.update(st)
        if st.get("running") and not alive:
            out["running"] = False
            out["stale"] = True
    return out
