"""Apeluri AI categorization — auto-learning din CTS (adevar de teren).

Mirror restrans pe calea legacy all-in-one din app/api/v1/ai_category.py (email), adaptat la
apeluri: nu exista corectii manuale (nu exista actiune "Corecteaza" pe modalul apelului), deci
singura sursa de semnal e divergenta fata de CTS (cts_calls_ground_truth vs calls.ai_category).
"""
import json
import logging
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import get_db
from app.api.v1.auth import get_current_admin
from app.services import call_classifier
from app.services import iris_ai

logger = logging.getLogger("mailguard.ai_call_category")
router = APIRouter()


def _load_call_cat_corr(db: Session):
    """Apeluri incadrate diferit fata de CTS (categorie), cu fragment de transcript pt context AI."""
    rows = db.execute(text(
        "SELECT c.ai_category AS old_category, gt.cts_category AS new_category, c.caller_number, "
        "LEFT(COALESCE(c.transcript, ''), 1600) AS snippet "
        "FROM cts_calls_ground_truth gt JOIN calls c ON c.id = gt.call_local_id "
        "WHERE gt.cts_category IS NOT NULL AND c.ai_category IS NOT NULL "
        "  AND gt.cts_category <> c.ai_category "
        "  AND gt.cts_category IN ('informatie','sesizare','reclamatie') "
        "ORDER BY gt.changed_at DESC NULLS LAST, gt.id DESC LIMIT 60")).fetchall()
    return [r._mapping for r in rows]


_REGEN_CALL_SYSTEM = (
    "Ești expert în prompt engineering pentru un clasificator de APELURI TELEFONICE de suport "
    "(transcript AGENT/CLIENT, nu email), care încadrează în 3 categorii: informatie, sesizare, "
    "reclamatie, pe baza unor reguli text per categorie. Primești regulile actuale și o listă de "
    "apeluri pe care clasificatorul le-a încadrat GREȘIT (categoria dată de AI vs categoria corectă "
    "confirmată de suport în CTS, cu fragment din transcript). "
    "Sarcina ta: RESCRIE COMPLET regulile pentru informatie/sesizare/reclamatie — produ un prompt nou, "
    "CURAT și CONSOLIDAT, care încorporează ce e încă valid din regulile actuale ȘI lecțiile din "
    "apelurile greșit încadrate. NU adăuga pur și simplu reguli noi peste cele vechi: ELIMINĂ "
    "redundanțele, regulile contradictorii, repetițiile și fragmentele învechite, comasează regulile "
    "care spun același lucru, și rescrie totul coerent de la zero. Rezultatul trebuie să fie mai clar și "
    "(de regulă) mai scurt decât intrarea, nu mai lung. Păstrează reguli GENERALE (NU hardcoda apeluri "
    "specifice, NU referi cazuri individuale). "
    "TIPAR RECURENT observat în apelurile greșit încadrate — tratează-l EXPLICIT în regulile rescrise: "
    "(a) Multe apeluri sunt clasificate SESIZARE doar pentru că apare un cuvânt de eroare/problemă "
    "('nu merge', 'eroare', 'blocat'), deși problema se REZOLVĂ CHIAR ÎN TIMPUL APELULUI prin ghidarea "
    "agentului (reinstalare aplicație, resetare parolă, deblocare cont, activare dispozitiv, prelungire "
    "termen de plată) și nu rămâne nimic nerezolvat la final — acestea trebuie să fie INFORMAȚIE, nu "
    "SESIZARE. Rezervă SESIZARE pentru probleme care rămân NEREZOLVATE la finalul apelului sau necesită "
    "intervenție ulterioară a altui departament/coleg. "
    "(b) O nemulțumire legată de o întârziere de câteva ORE în ACEEAȘI ZI (ex. 'am mai sunat azi și încă "
    "nu m-a contactat nimeni') NU este suficientă pentru RECLAMAȚIE — RECLAMAȚIA cere un eșec constatat "
    "de-a lungul mai multor ZILE sau apeluri anterioare DISTINCTE, nu doar impacientare pe termen scurt în "
    "cadrul aceleiași zile. "
    "Rețin totuși că sursa CTS conține și inconsistențe reale (același tip de scenariu poate fi etichetat "
    "diferit de operatori umani în cazuri diferite) — nu forța reguli extreme care ar produce alte erori "
    "in sens invers, echilibrează. "
    "Returnează DOAR JSON valid, fără ```, cu forma exactă: "
    '{"informatie":"<reguli complete rescrise>","sesizare":"<reguli complete rescrise>",'
    '"reclamatie":"<reguli complete rescrise>","explicatie":"<ce ai consolidat/eliminat, scurt, in romana>"}'
)


def _salvage_call_cat_json(raw):
    """Recupereaza dict-ul de prompturi pe categorie dintr-un raspuns AI ne-curat (oglinda
    ai_category._salvage_cat_json, aceleasi 4 chei)."""
    if not raw:
        return None
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    out = {}
    for key in ("informatie", "sesizare", "reclamatie", "explicatie"):
        mm = re.search(r'"' + key + r'"\s*:\s*"((?:[^"\\]|\\.)*)"', raw, re.DOTALL)
        if mm:
            frag = mm.group(1)
            try:
                out[key] = json.loads('"' + frag + '"')
            except Exception:
                out[key] = frag.replace('\\n', '\n').replace('\\"', '"').replace('\\\\', '\\').strip()
    return out or None


@router.post("/ai/call-category/regenerate-prompts")
def regenerate_call_prompts(body: dict = None, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Regenereaza prompturile de clasificare pentru apeluri pe baza divergentelor fata de CTS
    (adevarul de teren). Un singur apel AI, toate cele 3 categorii deodata (mirror pe calea legacy
    all-in-one din ai_category.py). NU salveaza automat."""
    if not iris_ai.is_configured():
        raise HTTPException(400, "IRIS AI neconfigurat (lipsește IRIS_AI_KEY)")
    body = body or {}
    _model = (body.get("model") or "claude-haiku-4-5-20251001").strip()
    prompts = call_classifier.load_call_prompts()
    corr = _load_call_cat_corr(db)
    if not corr:
        raise HTTPException(400, "Nicio divergență față de CTS (categorie) — nimic de regenerat")

    lines = ["REGULILE ACTUALE PE CATEGORIE:"]
    for c in call_classifier.EDITABLE:
        lines.append("\n=== " + c.upper() + " ===\n" + prompts[c])
    lines.append("\n\nAPELURI ÎNCADRATE GREȘIT (transcript AGENT/CLIENT):")
    for i, m in enumerate(corr, 1):
        lines.append("\n[" + str(i) + "] AI a zis: " + str(m["old_category"]) +
                     " | CORECT (CTS): " + str(m["new_category"]) +
                     "\nTelefon: " + (m["caller_number"] or "(gol)") +
                     "\nFragment transcript: " + (m["snippet"] or "").strip())
    content = "\n".join(lines)

    res = iris_ai.run_prompt(_REGEN_CALL_SYSTEM, content, response_format="json",
                             model_hint=_model, temperature=0.2,
                             max_tokens=8000, task="cargo360:call_cat_prompt_regen", no_cache=True)
    parsed = res.get("parsed")
    if not isinstance(parsed, dict) or not parsed:
        err = res.get("error") if isinstance(res.get("error"), dict) else {}
        raw = res.get("text") or err.get("raw_text") or ""
        parsed = _salvage_call_cat_json(raw) or {}
    suggested = {}
    for c in call_classifier.EDITABLE:
        v = parsed.get(c) if isinstance(parsed, dict) else None
        if isinstance(v, str) and v.strip():
            suggested[c] = v.strip()
    if not suggested:
        if not res.get("ok"):
            raise HTTPException(502, "Regenerare eșuată: " + str(res.get("error")))
        raise HTTPException(502, "AI nu a returnat prompturi valide")
    return {"ok": True, "suggested": suggested,
            "explicatie": (parsed.get("explicatie") if isinstance(parsed, dict) else None),
            "based_on": len(corr), "model": res.get("model"), "usage": res.get("usage")}


@router.post("/ai/call-category/reclassify-one/{call_id}")
def reclassify_one_call(call_id: int, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Reclasifica UN SINGUR apel divergent fata de CTS, cu prompturile CURENTE (proaspat salvate
    din DB), si compara vechea vs noua categorie fata de adevarul CTS. Endpoint pe-apel (nu bulk):
    reclasificarea bulk sincrona pe zeci de apeluri, fiecare cu no_cache=True (raspuns AI proaspat,
    nu din cache-ul curated), depaseste timeout-ul frontend (75s) — frontend-ul itereaza acest
    endpoint apel-cu-apel, cu progres live, in loc de un singur request lung."""
    if not iris_ai.is_configured():
        raise HTTPException(400, "IRIS AI neconfigurat (lipsește IRIS_AI_KEY)")
    row = db.execute(text(
        "SELECT c.caller_number, c.transcript, c.ai_category AS old_category, "
        "gt.cts_category AS cts_category "
        "FROM cts_calls_ground_truth gt JOIN calls c ON c.id = gt.call_local_id "
        "WHERE gt.call_local_id = :id AND gt.cts_category IS NOT NULL AND c.ai_category IS NOT NULL"),
        {"id": call_id}).fetchone()
    if not row:
        raise HTTPException(404, "Apelul nu are divergență CTS activă (poate a fost deja reclasificat)")
    m = row._mapping
    transcript, old_cat, cts_cat = m["transcript"], m["old_category"], m["cts_category"]
    new_res = call_classifier.classify_call(transcript, no_cache=True)
    if not new_res:
        raise HTTPException(502, "Clasificare eșuată (IRIS AI indisponibil)")
    new_cat = new_res.get("category")
    db.execute(text(
        "UPDATE calls SET ai_category=:cat, ai_tone=:tone, ai_result=CAST(:r AS jsonb), "
        "updated_at=now() WHERE id=:id"),
        {"cat": new_cat, "tone": new_res.get("tone"), "r": json.dumps(new_res), "id": call_id})
    db.commit()
    return {"ok": True, "call_id": call_id, "caller_number": m["caller_number"],
            "old_category": old_cat, "new_category": new_cat,
            "cts_category": cts_cat, "now_matches": (new_cat == cts_cat)}
