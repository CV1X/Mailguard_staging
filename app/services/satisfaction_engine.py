"""Motor de scor satisfacție client — v2, bazat pe interaction_analysis.

4 piloni (A/B/C/D) calculați din câmpurile AI bogate per interacțiune:
  A. Emoție        30% — WSS, trend sentiment, negativitate intensă
  B. Efort client  25% — repeat issues, CPI, follow-up nesolicitate
  C. Operațional   25% — rata rezoluție, promisiuni încălcate, taskuri
  D. Relație       20% — warmth delta, formality delta, frecvență, engagement

Fereastra: 90 zile. Decay temporal: half-life 45 zile (w = 0.5^(zile/45)).
Override post-calcul: red flags critice forțează segment indiferent de scor.
"""

import json
import logging
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.services.category_classifier import _email_body

logger = logging.getLogger("mailguard.satisfaction")

_WINDOW_DAYS = 90
_WINDOW_RECENT_DAYS = 60
_HALF_LIFE_DAYS = 45.0

_PILON_WEIGHTS = {
    "emotion": 0.30,
    "effort": 0.25,
    "operational": 0.25,
    "relationship": 0.20,
}

_RED_FLAGS_CRITIC_30D = {"mentiune_reziliere", "amenintare_legala", "ultimatum", "escaladare_management"}
_RED_FLAGS_RISK_60D = {"mentiune_concurenta", "mentiune_penalitati_contract", "cerere_export_date"}

_RESOLVED_STATUSES = {"resolved", "closed", "done", "solved", "rezolvat", "inchis"}
_RESOLVED_SIGNALS_EMAIL = {"rezolvat"}
_RESOLVED_SIGNALS_CALL = {"rezolvat_pe_loc"}


# ── Prompt IRIS — scor de satisfacție AI-first ─────────────────────────────────
# IRIS dă scorul PRIMAR (0-100). Calculul determinist trece doar ca CONTEXT informativ,
# NU ca ancoră. Sursă unică folosită și de endpoint-ul buton, și de snapshot-ul lunar.
SATISFACTION_SYSTEM = """Ești un analist senior de satisfacție clienți B2B cu 15 ani experiență în servicii logistice/fleet management.
Primești textul BRUT al comunicărilor unui client (transcrieri apeluri telefonice + emailuri) și evaluezi satisfacția reală.

PRINCIPIU FUNDAMENTAL:
Analizezi CE A ZIS clientul efectiv. Scorul pornește de la 100 și scade NUMAI dacă identifici în text dovezi concrete și explicite de nemulțumire față de serviciu.

CONTEXT B2B LOGISTIC — CE ESTE COMPLET NORMAL ȘI NU AFECTEAZĂ SCORUL:
- Multe interacțiuni consecutive pe aceeași temă (activare dispozitiv, taxe drum, montaj echipament) → problemă tehnică în curs de rezolvare, NU insatisfacție
- Ton neutru sau scurt în apeluri → normalul unui context operațional sub presiune de timp
- Urgență operațională (șofer blocat, tichet neactivat, eroare echipament) → problemă tehnică punctuală
- Client trimite documente, facturi, confirmări → client cooperant și implicat = bine
- Frustrare față de o problemă tehnică specifică (nu față de companie în general) → incident operațional normal
- Menționarea unui alt furnizor în context informativ sau tehnic ("fostul furnizor", "la Eurovac era activat") → nu e amenințare de plecare
- Client sună să întrebe stadiul unei cereri → follow-up normal, nu eșec

MOTIVE ECONOMICE / EXTERNE — REGULĂ OBLIGATORIE (NU SCAD SCORUL NICIODATĂ):
Dacă clientul cere încetarea, suspendarea sau reducerea contractului din motive care NU au legătură cu
calitatea serviciilor CargoTrack, satisfacția NU scade și clientul NU se marchează ca nemulțumit sau la risc.
Astfel de motive, chiar când duc la pierderea contractului, sunt EXTERNE:
- intră în insolvență, faliment, reorganizare judiciară, executare silită, blocaj financiar
- nu mai are bani / probleme de lichiditate / nu poate plăti facturile / cere reeșalonare
- vinde firma, fuziune, schimbare de acționariat, închide activitatea de transport
- vinde camioanele, reduce flota, casează sau imobilizează vehicule
- accidente, daune totale, furt sau avarierea vehiculului → mașina nu mai poate fi folosită
- expirarea/încetarea unui contract de leasing sau a unei curse/proiect punctual
- restructurare internă, activitate sezonieră redusă, șomaj tehnic
În aceste cazuri: satisfaction_pct rămâne în zona normală (nu penalizezi), red_flags_confirmed = [],
iar în `reasoning` scrii explicit că încetarea are cauză economică/externă, NU nemulțumire față de servicii.
Excepție unică: dacă, PE LÂNGĂ motivul economic, clientul reproșează EXPLICIT și calitatea serviciului
CargoTrack, atunci evaluezi doar acel reproș explicit — nu situația financiară.

SINGURELE DOVEZI CARE SCAD SCORUL (trebuie să apară EXPLICIT în text, nu inferit):
1. Clientul declară explicit că vrea să plece sau să rezilieze contractul DIN NEMULȚUMIRE față de
   serviciile CargoTrack (dacă motivul e economic/extern — insolvență, lipsă de bani, vânzare firmă
   sau camioane, accident — vezi regula „MOTIVE ECONOMICE / EXTERNE": NU scade scorul)
2. Clientul menționează un concurent CA ALTERNATIVĂ ACTIVĂ, nu informativ ("mă duc la X dacă nu rezolvați AZI")
3. Aceeași problemă PRINCIPALĂ a serviciului (nu o problemă tehnică punctuală) nerezolvată luni de zile cu client frustrat repetat
4. Amenințare legală sau escaladare la conducere CargoTrack explicită
5. Nemulțumire generală și repetată față de calitatea SERVICIULUI (nu față de un incident tehnic)

IMPORTANT — DISTINCȚIE CRITICĂ:
"Problema nu e rezolvată după 3 săptămâni" pe UN dispozitiv specific = incident tehnic, NU insatisfacție față de serviciu.
"Sunt nemulțumit de modul în care lucrați în general" = insatisfacție reală față de serviciu.

Scala:
- Interacțiuni operaționale/tehnice normale, chiar frecvente → 88-100
- Un incident tehnic nerezolvat rapid, cu client ușor frustrat dar cooperant → 75-87
- Frustrare reală față de serviciu (nu doar față de un incident), repetată în mai multe apeluri distincte → 55-74
- Amenințare explicită de plecare, mențiune concurență ca alternativă reală → 35-54
- Intenție clară de reziliere sau escaladare legală confirmată → sub 35

NOTA despre red_flags_detectate_algoritmic: detectate automat din cuvinte-cheie, foarte des FALS POZITIVE.
Validează FIECARE pe baza textului — dacă contextul nu confirmă riscul real, pune [] în red_flags_confirmed.

Returnează STRICT JSON, fără alt text:
{
  "satisfaction_pct": <float 0-100 cu 1 zecimală>,
  "confidence": <float 0-1>,
  "reasoning": <string 2-3 propoziții CONCRETE în română — citează ce anume din text a influențat scorul, cu exemple reale din mesaje>,
  "red_flags_confirmed": <lista STRICTĂ — doar flag-uri din red_flags_detectate_algoritmic confirmate cu dovadă textuală clară; [] în caz de îndoială>
}"""


def _decay(age_days: float) -> float:
    return math.exp(-math.log(2) * age_days / _HALF_LIFE_DAYS)


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _age_days(ts, now: datetime) -> float:
    if ts is None:
        return 0.0
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts)
        except Exception:
            return 0.0
    if hasattr(ts, "tzinfo") and ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    delta = now - ts
    return max(0.0, delta.total_seconds() / 86400.0)


def _first(row):
    if row is None:
        return None
    if hasattr(row, "values"):
        return list(row.values())[0]
    return row[0]


def _row_get(row, *keys):
    if hasattr(row, "keys"):
        return tuple(row.get(k) for k in keys)
    return tuple(row[i] for i in range(len(keys)))


def _fetch_interactions(client_id: int, cur, now: datetime, window_days: int = _WINDOW_DAYS) -> List[dict]:
    """Citește toate înregistrările din interaction_analysis pentru client, fereastră dată."""
    since = now - timedelta(days=window_days)
    try:
        cur.execute(
            """
            SELECT analysis_json, sentiment_score, occurred_at, direction, interaction_type
            FROM interaction_analysis
            WHERE client_id = %s
              AND occurred_at >= %s
            ORDER BY occurred_at DESC
            LIMIT 300
            """,
            (client_id, since),
        )
        rows = cur.fetchall()
        result = []
        for row in rows:
            analysis_json, sentiment_score, occurred_at, direction, itype = _row_get(
                row, "analysis_json", "sentiment_score", "occurred_at", "direction", "interaction_type"
            )
            aj = analysis_json
            if isinstance(aj, str):
                try:
                    aj = json.loads(aj)
                except Exception:
                    aj = {}
            elif aj is None:
                aj = {}
            result.append({
                "analysis": aj,
                "sentiment_score": sentiment_score,
                "occurred_at": occurred_at,
                "direction": direction or "inbound",
                "interaction_type": itype or "",
                "age_days": _age_days(occurred_at, now),
            })
        return result
    except Exception:
        logger.warning("satisfaction_engine: nu am putut citi interaction_analysis pentru client_id=%s", client_id, exc_info=True)
        return []


# ── PILON A: Emoție ───────────────────────────────────────────────────────────

def _pillar_emotion(interactions: List[dict]) -> Tuple[float, dict]:
    """A1 WSS + A2 Trend + A3 Negativitate intensă → scor 0-100."""
    inbound = [i for i in interactions if i["direction"] == "inbound"]
    if not inbound:
        return 50.0, {"wss": 50.0, "trend": 50.0, "neg_rate": 100.0, "data_points": 0}

    # A1: WSS — Weighted Sentiment Score
    w_sum = 0.0
    w_total = 0.0
    for item in inbound:
        s = item["analysis"].get("sentiment")
        if s is None:
            s = item.get("sentiment_score")
        if s is None:
            continue
        s = float(s)
        d = _decay(item["age_days"])
        w_sum += s * d
        w_total += d

    wss_raw = (w_sum / w_total) if w_total > 0 else 0.0  # -1..1
    # Baza 60, scalare asimetrică: pozitivul e răsplătit mai generos decât
    # penalizează negativul. Neutru (0)=60, +0.5≈87, +1=100, -0.5≈40, -1=20.
    # Motiv: LLM-ul rareori dă >+0.5; sentiment ușor pozitiv real trebuie să iasă bine.
    if wss_raw >= 0:
        wss = _clamp(wss_raw * 55 + 60)
    else:
        wss = _clamp(wss_raw * 40 + 60)

    # A2: Trend — regresie liniară pe sentimentele zilnice (90 zile)
    # Grupare pe zi, media zilei, pantă (puncte/zi) → normalizat 50 + clamp(m*900, -50, +50)
    daily: Dict[str, list] = {}
    for item in inbound:
        s = item["analysis"].get("sentiment")
        if s is None:
            s = item.get("sentiment_score")
        if s is None:
            continue
        oa = item["occurred_at"]
        if oa is None:
            continue
        if hasattr(oa, "date"):
            day_key = str(oa.date())
        else:
            day_key = str(oa)[:10]
        daily.setdefault(day_key, []).append(float(s))

    trend_score = 65.0
    # Prag minim de zile distincte: sub 4 zile, panta e zgomot pur (outlier de o zi
    # o poate răsturna). Fără tendință măsurabilă = stabil (65), nu suspect.
    if len(daily) >= 4:
        days_sorted = sorted(daily.keys())
        xs = []
        ys = []
        for dk in days_sorted:
            try:
                from datetime import date as _date
                d0 = _date.fromisoformat(days_sorted[0])
                di = _date.fromisoformat(dk)
                xi = (di - d0).days
            except Exception:
                xi = len(xs)
            xs.append(float(xi))
            ys.append(sum(daily[dk]) / len(daily[dk]))
        n = len(xs)
        xmean = sum(xs) / n
        ymean = sum(ys) / n
        num = sum((xs[i] - xmean) * (ys[i] - ymean) for i in range(n))
        den = sum((xs[i] - xmean) ** 2 for i in range(n))
        slope = num / den if den != 0 else 0.0  # sentiment units/day
        # Bază 65 (stabil/fără înrăutățire = bine, nu 50). Deadband lat (0.008/zi):
        # zgomotul obișnuit nu mișcă scorul. Asimetric: îmbunătățirea urcă repede,
        # doar o înrăutățire CLARĂ și susținută coboară — un outlier nu prăbușește trendul.
        if abs(slope) < 0.008:
            trend_score = 65.0
        elif slope > 0:
            trend_score = _clamp(65 + min(35, slope * 500))
        else:
            trend_score = _clamp(65 + max(-45, slope * 400))

    # A3: Rata negativitate intensă (60 zile, inbound)
    since_60 = None
    recent_inbound = [i for i in inbound if i["age_days"] <= 60]
    neg_intense_count = 0
    for item in recent_inbound:
        s = item["analysis"].get("sentiment", 0.0) or 0.0
        ei = item["analysis"].get("emotional_intensity", 0.0) or 0.0
        if float(s) < -0.3 and float(ei) > 0.6:
            # Service recovery discount: dacă în ≤5 zile urmează resolution_signal pozitiv
            # Simplificat: verificăm câmpul resolution_signal din aceeași interacțiune
            rs = item["analysis"].get("resolution_signal", "")
            if rs in ("rezolvat", "rezolvat_pe_loc"):
                neg_intense_count += 0.3
            else:
                neg_intense_count += 1.0

    total_recent = len(recent_inbound)
    neg_rate_score = 100.0
    if total_recent > 0:
        ratio = neg_intense_count / total_recent
        # 100 × (1 - ratio × 2.5), clamp 0-100
        neg_rate_score = _clamp(100.0 * (1.0 - ratio * 2.5))

    # Media pilonului A
    score = (wss * 0.40 + trend_score * 0.35 + neg_rate_score * 0.25)

    return _clamp(score), {
        "wss": round(wss, 1),
        "trend": round(trend_score, 1),
        "neg_rate": round(neg_rate_score, 1),
        "data_points": len(inbound),
    }


# ── PILON B: Efort client ─────────────────────────────────────────────────────

def _pillar_effort(interactions: List[dict]) -> Tuple[float, dict]:
    """B1 Repeat Issue Rate + B3 CPI + B4 Follow-up nesolicitate → scor 0-100."""
    inbound = [i for i in interactions if i["direction"] == "inbound"]
    if not inbound:
        return 70.0, {"repeat_issue": 100.0, "cpi": 100.0, "data_points": 0}

    # B1: Rata repeat issues
    problem_related = [i for i in inbound if i["analysis"].get("problem_related")]
    repeat_count = sum(1 for i in problem_related if i["analysis"].get("is_repeat_issue"))
    if problem_related:
        rrate = repeat_count / len(problem_related)
        # <10% bun→100, 10-25% atenție→liniar 100-50, >25% critic→<50
        if rrate < 0.10:
            b1 = 100.0
        elif rrate <= 0.25:
            b1 = 100.0 - (rrate - 0.10) / 0.15 * 50.0
        else:
            b1 = _clamp(50.0 - (rrate - 0.25) * 200.0)
    else:
        b1 = 80.0  # fără probleme semnalate = OK

    # B3: CPI — contacte per problemă
    # Grupare simplă: probleme distincte = set de problem_description non-null
    problems: Dict[str, int] = {}
    for item in inbound:
        desc = item["analysis"].get("problem_description")
        if desc and len(str(desc)) > 5:
            key = str(desc)[:80].lower().strip()
            problems[key] = problems.get(key, 0) + 1
        elif item["analysis"].get("problem_related"):
            problems["_generic_" + str(item["occurred_at"])[:10]] = 1

    total_problem_interactions = sum(problems.values())
    n_distinct_problems = len(problems)
    if n_distinct_problems > 0:
        cpi = total_problem_interactions / n_distinct_problems
        # ≤2 excelent→100, 3-4 acceptabil→60-80, ≥5 efort mare→<40
        if cpi <= 2:
            b3 = 100.0
        elif cpi <= 4:
            b3 = 100.0 - (cpi - 2) / 2 * 40.0
        else:
            b3 = _clamp(60.0 - (cpi - 4) * 15.0)
    else:
        b3 = 90.0

    # B4 (First Contact Resolution) ELIMINAT 2026-07-17: nu se putea distinge fiabil
    # un reply/schimb de documente normal de o insistență reală pe o problemă.
    # Efortul se măsoară acum doar prin repeat_issue (B1) + CPI (B3).
    score = (b1 * 0.55 + b3 * 0.45)

    return _clamp(score), {
        "repeat_issue": round(b1, 1),
        "cpi": round(b3, 1),
        "data_points": len(inbound),
    }


# ── PILON C: Operațional ──────────────────────────────────────────────────────

def _pillar_operational(client_id: int, iris_client_id, interactions: List[dict], cur, now: datetime) -> Tuple[float, dict]:
    """C1 Rezoluție + C3 Promisiuni încălcate + C5/C6 Taskuri → scor 0-100."""

    # Semnale de rezoluție: DOAR "nerezolvat" e eșec real.
    # "promisiune_follow_up" / "in_lucru" = în curs (neutru, NU penalizat) — o problemă
    # care încă nu s-a închis NU înseamnă că nu e rezolvată deloc.
    _RESOLVED = ("rezolvat", "rezolvat_pe_loc")
    _FAILED = ("nerezolvat",)  # singurul verdict negativ definitiv

    # C1: Rata de rezoluție — se calculează DOAR pe problemele cu verdict definitiv
    # (rezolvat vs nerezolvat). Cele "în curs" (follow_up / in_lucru) se exclud din numitor.
    # Probleme din >7 zile (cele din ultimele 7 zile se exclud — în lucru legitim)
    old_interactions = [i for i in interactions if i["age_days"] > 7]
    problem_old = [i for i in old_interactions if i["analysis"].get("problem_related")]
    decided = [
        i for i in problem_old
        if (i["analysis"].get("resolution_signal") or "") in (_RESOLVED + _FAILED)
    ]
    if decided:
        resolved_count = sum(
            1 for i in decided
            if (i["analysis"].get("resolution_signal") or "") in _RESOLVED
        )
        res_rate = resolved_count / len(decided)
        # ≥90% bun, 75-89% atenție, <75% critic
        if res_rate >= 0.90:
            c1 = 100.0
        elif res_rate >= 0.75:
            c1 = 60.0 + (res_rate - 0.75) / 0.15 * 40.0
        else:
            c1 = _clamp(res_rate / 0.75 * 60.0)
    else:
        c1 = 85.0  # fără verdict definitiv (doar probleme în curs sau fără probleme) = neutru

    # C3: Promisiuni încălcate — o promisiune e "încălcată" DOAR dacă interacțiunea e mai
    # veche de 3 zile ȘI a primit verdict explicit "nerezolvat". Un follow_up promis sau
    # ceva încă "in_lucru" NU e o promisiune încălcată — e muncă în desfășurare.
    broken_count = 0
    for item in interactions:
        promises = item["analysis"].get("promises_made") or []
        if not promises:
            continue
        if item["age_days"] < 3:
            continue  # prea recente, nu le numărăm
        rs = (item["analysis"].get("resolution_signal") or "")
        if rs in _FAILED:
            broken_count += len(promises)

    # Normalizare: 0→100, 1→60, 2→30, ≥3→0
    if broken_count == 0:
        c3 = 100.0
    elif broken_count == 1:
        c3 = 60.0
    elif broken_count == 2:
        c3 = 30.0
    else:
        c3 = 0.0

    # C5/C6: Taskuri (dacă avem iris_client_id)
    tasks_score = 80.0  # default neutru dacă nu avem date
    if iris_client_id:
        try:
            since_90 = now - timedelta(days=90)
            # C5: reopened tasks
            cur.execute(
                """
                SELECT COUNT(*) FROM cts_task_ground_truth
                WHERE client_id = %s
                  AND LOWER(status) = 'reopened'
                  AND cts_created_at >= %s
                """,
                (iris_client_id, since_90),
            )
            reopened = _first(cur.fetchone()) or 0

            cur.execute(
                """
                SELECT COUNT(*) FROM cts_task_ground_truth
                WHERE client_id = %s
                  AND LOWER(status) = ANY(%s)
                  AND cts_created_at >= %s
                """,
                (iris_client_id, list(_RESOLVED_STATUSES), since_90),
            )
            closed = _first(cur.fetchone()) or 0

            # C6: overdue (deschise > 14 zile)
            overdue_cutoff = now - timedelta(days=14)
            cur.execute(
                """
                SELECT COUNT(*) FROM cts_task_ground_truth
                WHERE client_id = %s
                  AND LOWER(status) != ALL(%s)
                  AND cts_created_at <= %s
                """,
                (iris_client_id, list(_RESOLVED_STATUSES), overdue_cutoff),
            )
            overdue = _first(cur.fetchone()) or 0

            cur.execute(
                """
                SELECT COUNT(*) FROM cts_task_ground_truth
                WHERE client_id = %s
                  AND LOWER(status) != ALL(%s)
                """,
                (iris_client_id, list(_RESOLVED_STATUSES)),
            )
            open_total = _first(cur.fetchone()) or 0

            # C5: reopen rate
            if closed > 0:
                reopen_rate = (reopened or 0) / closed
                c5 = _clamp(100.0 - reopen_rate * 500.0)
            else:
                c5 = 90.0

            # C6: overdue rate
            if open_total > 0:
                overdue_rate = overdue / open_total
                c6 = _clamp(100.0 - overdue_rate * 150.0)
            else:
                c6 = 100.0 if overdue == 0 else 50.0

            tasks_score = (c5 * 0.5 + c6 * 0.5)
        except Exception:
            logger.warning("satisfaction_engine: eroare taskuri pentru client_id=%s", client_id, exc_info=True)

    score = (c1 * 0.40 + c3 * 0.35 + tasks_score * 0.25)

    return _clamp(score), {
        "resolution_rate": round(c1, 1),
        "broken_promises": round(c3, 1),
        "tasks_score": round(tasks_score, 1),
        "data_points": len(old_interactions),
    }


# ── PILON D: Relație ──────────────────────────────────────────────────────────

def _pillar_relationship(interactions: List[dict]) -> Tuple[float, dict]:
    """D1 Warmth delta + D2 Formality delta + D3 Frecvență + D4 Future orientation + D6 Engagement."""
    inbound = [i for i in interactions if i["direction"] == "inbound"]
    if not inbound:
        return 50.0, {"warmth_delta": 50.0, "formality_delta": 50.0, "frequency": 50.0, "engagement": 50.0, "data_points": 0}

    # Baseline: primele 50% din interacțiunile sortate cronologic (cele mai vechi)
    sorted_inbound = sorted(inbound, key=lambda x: x["age_days"], reverse=True)
    split = max(1, len(sorted_inbound) // 2)
    baseline_items = sorted_inbound[split:]  # mai vechi
    recent_items = [i for i in inbound if i["age_days"] <= 60]  # ultimele 60 zile

    def _mean(items, field, default=0.5):
        vals = [float(i["analysis"].get(field, default) or default) for i in items if i["analysis"].get(field) is not None]
        return sum(vals) / len(vals) if vals else default

    baseline_warmth = _mean(baseline_items, "message_warmth", 0.5)
    recent_warmth = _mean(recent_items or inbound[:10], "message_warmth", 0.5)
    baseline_formality = _mean(baseline_items, "formality_level", 0.5)
    recent_formality = _mean(recent_items or inbound[:10], "formality_level", 0.5)

    # D1: Warmth — ton stabil/normal = bine (bază 80). Doar o SCĂDERE clară de căldură
    # (client care se răcește vizibil față de trecut) penalizează. Creșterea urcă ușor.
    # Tonul tranzacțional politicos NU e "rece" — e normalul B2B.
    warmth_delta = recent_warmth - baseline_warmth  # -1..+1
    if warmth_delta >= -0.10:
        d1 = _clamp(80.0 + max(0.0, warmth_delta) * 40.0)  # stabil/mai cald = 80-100
    else:
        d1 = _clamp(80.0 + (warmth_delta + 0.10) * 120.0)  # răcire reală penalizează

    # D2: Formality delta — DOAR o creștere MARE de formalitate e semnal (distanțare/răcire).
    # Formalitatea în business e normală; o mică variație sau scăderea NU se penalizează.
    # Bază 100; se scade doar peste un prag mort de +0.15, cu pantă blândă.
    formality_delta = recent_formality - baseline_formality
    if formality_delta <= 0.15:
        d2 = 100.0  # stabil, mai puțin formal, sau creștere mică = normal
    else:
        d2 = _clamp(100.0 - (formality_delta - 0.15) * 120.0)

    # D3: Frecvență comunicare — comparăm recent vs baseline
    total_interactions = len(inbound)
    if total_interactions > 0:
        baseline_rate = len(baseline_items) / max(1, _WINDOW_DAYS - 60)
        recent_rate = len(recent_items) / 60.0
        if baseline_rate > 0:
            freq_index = recent_rate / baseline_rate
            # index ≥0.8 → 100, 0.4-0.8 → liniar, <0.4 → 0 (semnal tăcere dezangajare)
            if freq_index >= 0.8:
                d3 = 100.0
            elif freq_index >= 0.4:
                d3 = (freq_index - 0.4) / 0.4 * 100.0
            else:
                d3 = 0.0
        else:
            d3 = 70.0
    else:
        d3 = 50.0

    # D4: Future orientation
    baseline_fo = sum(1 for i in baseline_items if i["analysis"].get("future_orientation")) / max(1, len(baseline_items))
    recent_fo = sum(1 for i in (recent_items or inbound)) if True else 0
    recent_fo_rate = sum(1 for i in (recent_items or inbound) if i["analysis"].get("future_orientation")) / max(1, len(recent_items or inbound))
    fo_delta = recent_fo_rate - baseline_fo
    d4 = _clamp(50.0 + fo_delta * 100.0)

    # D6: Engagement — asks_questions rate vs baseline + message_length_signal
    baseline_aq = sum(1 for i in baseline_items if i["analysis"].get("asks_questions")) / max(1, len(baseline_items))
    recent_list = recent_items or inbound
    recent_aq = sum(1 for i in recent_list if i["analysis"].get("asks_questions")) / max(1, len(recent_list))
    aq_delta = recent_aq - baseline_aq
    baseline_mls = _mean(baseline_items, "message_length_signal", 0.5)
    recent_mls = _mean(recent_list, "message_length_signal", 0.5)
    mls_delta = recent_mls - baseline_mls
    # D6: Engagement — bază 75 (client care răspunde = angajat). Lungimea mesajului
    # și inițiativa sunt DOAR utile, nu deterministe (user): un client concis nu e
    # dezangajat. Penalizăm doar o scădere clară de implicare față de trecut.
    combined_delta = aq_delta + mls_delta
    if combined_delta >= -0.15:
        d6 = _clamp(75.0 + max(0.0, combined_delta) * 40.0)
    else:
        d6 = _clamp(75.0 + (combined_delta + 0.15) * 90.0)

    score = (d1 * 0.25 + d2 * 0.25 + d3 * 0.20 + d4 * 0.15 + d6 * 0.15)

    return _clamp(score), {
        "warmth_delta": round(d1, 1),
        "formality_delta": round(d2, 1),
        "frequency": round(d3, 1),
        "engagement": round(d6, 1),
        "data_points": len(inbound),
    }


# ── Red flags ────────────────────────────────────────────────────────────────

def _collect_red_flags(interactions: List[dict], now: datetime) -> Tuple[List[str], str]:
    """Colectează red flags din interaction_analysis. Returnează (flags_active, override_segment)."""
    flags_30d: set = set()
    flags_60d: set = set()
    for item in interactions:
        flags = item["analysis"].get("red_flags") or []
        age = item["age_days"]
        for f in flags:
            if age <= 30:
                flags_30d.add(f)
            if age <= 60:
                flags_60d.add(f)

    override = ""
    if flags_30d & _RED_FLAGS_CRITIC_30D:
        override = "critic"
    elif flags_60d & _RED_FLAGS_RISK_60D:
        override = "la_risc"

    all_flags = list(flags_30d | flags_60d)
    return all_flags, override


def _segment(score: float) -> str:
    if score >= 70:
        return "sanatos"
    if score >= 45:
        return "neutru"
    if score >= 25:
        return "la_risc"
    return "critic"


def _segment_min(current: str, minimum: str) -> str:
    order = ["sanatos", "neutru", "la_risc", "critic"]
    ci = order.index(current) if current in order else 0
    mi = order.index(minimum) if minimum in order else 0
    return order[max(ci, mi)]


# ── Funcție principală ────────────────────────────────────────────────────────

def compute_satisfaction(
    client_id: int,
    iris_client_id: Optional[int],
    cur,
    now: datetime,
    *,
    skip_exclude_check: bool = False,
) -> dict:
    """Calculează scorul de satisfacție pentru un client (v2, 4 piloni).

    Interfața externă e identică cu v1 — returnează același dict pentru compatibilitate
    cu satisfaction_snapshot.py și endpoint-ul estimate-satisfaction.
    """
    if not skip_exclude_check:
        try:
            cur.execute("SELECT satisfaction_exclude FROM clients WHERE id = %s", (client_id,))
            row = cur.fetchone()
            if row:
                val = _first(row)
                if val:
                    return {
                        "satisfaction_pct": None,
                        "is_unsatisfied": False,
                        "breakdown": {},
                        "config_used": {"version": "v2", "pillars": _PILON_WEIGHTS},
                        "computed_at": now.isoformat(),
                        "error": "excluded",
                    }
        except Exception:
            pass

    interactions = _fetch_interactions(client_id, cur, now, _WINDOW_DAYS)

    if not interactions:
        return {
            "satisfaction_pct": None,
            "is_unsatisfied": False,
            "breakdown": {},
            "config_used": {"version": "v2", "pillars": _PILON_WEIGHTS},
            "computed_at": now.isoformat(),
            "error": "no_data",
        }

    # Clienți cu sub 2 interacțiuni în fereastra de analiză → skip (date insuficiente)
    if len(interactions) < 2:
        return {
            "satisfaction_pct": None,
            "is_unsatisfied": False,
            "breakdown": {},
            "config_used": {"version": "v2", "pillars": _PILON_WEIGHTS},
            "computed_at": now.isoformat(),
            "error": "insufficient_data",
        }

    # Confidence: min(1, nr_interacțiuni/15) × min(1, zile_istoric/90)
    oldest_age = max((i["age_days"] for i in interactions), default=0)
    conf_volume = min(1.0, len(interactions) / 15.0)
    conf_history = min(1.0, oldest_age / 90.0)
    confidence = conf_volume * conf_history

    # Calcul piloni
    score_a, sub_a = _pillar_emotion(interactions)
    score_b, sub_b = _pillar_effort(interactions)
    score_c, sub_c = _pillar_operational(client_id, iris_client_id, interactions, cur, now)
    score_d, sub_d = _pillar_relationship(interactions)

    chs = (
        score_a * _PILON_WEIGHTS["emotion"] +
        score_b * _PILON_WEIGHTS["effort"] +
        score_c * _PILON_WEIGHTS["operational"] +
        score_d * _PILON_WEIGHTS["relationship"]
    )

    satisfaction_pct = round(_clamp(chs), 1)

    # Red flags + override segment
    red_flags_active, override_segment = _collect_red_flags(interactions, now)
    seg = _segment(satisfaction_pct)
    if override_segment == "critic":
        seg = "critic"
    elif override_segment == "la_risc":
        seg = _segment_min(seg, "la_risc")

    # Threshold nesatisfăcut: 70 (echivalent segmentului "neutru"/"la_risc"/"critic")
    is_unsatisfied = satisfaction_pct < 70.0

    breakdown = {
        "emotion": {
            "score": round(score_a / 100.0, 4),
            "weight": _PILON_WEIGHTS["emotion"],
            "contribution": round(score_a * _PILON_WEIGHTS["emotion"] / 100.0, 4),
            "data_points": sub_a.get("data_points", 0),
            "sub": sub_a,
        },
        "effort": {
            "score": round(score_b / 100.0, 4),
            "weight": _PILON_WEIGHTS["effort"],
            "contribution": round(score_b * _PILON_WEIGHTS["effort"] / 100.0, 4),
            "data_points": sub_b.get("data_points", 0),
            "sub": sub_b,
        },
        "operational": {
            "score": round(score_c / 100.0, 4),
            "weight": _PILON_WEIGHTS["operational"],
            "contribution": round(score_c * _PILON_WEIGHTS["operational"] / 100.0, 4),
            "data_points": sub_c.get("data_points", 0),
            "sub": sub_c,
        },
        "relationship": {
            "score": round(score_d / 100.0, 4),
            "weight": _PILON_WEIGHTS["relationship"],
            "contribution": round(score_d * _PILON_WEIGHTS["relationship"] / 100.0, 4),
            "data_points": sub_d.get("data_points", 0),
            "sub": sub_d,
        },
        "red_flags_active": red_flags_active,
        "segment": seg,
        "confidence": round(confidence, 3),
        "total_interactions": len(interactions),
    }

    return {
        "satisfaction_pct": satisfaction_pct,
        "is_unsatisfied": is_unsatisfied,
        "breakdown": breakdown,
        "config_used": {"version": "v2", "pillars": _PILON_WEIGHTS},
        "computed_at": now.isoformat(),
        **({"error": "low_confidence"} if confidence < 0.5 else {}),
    }


def _collect_raw_interactions(client_id: int, cur, now: datetime, limit: int = 20) -> List[dict]:
    """Textul brut al interacțiunilor (90 zile) — emails + calls — pentru analiza directă IRIS.

    IRIS judecă pe textul real, nu pe metricile pre-calculate. Returnează lista de dicts cu:
    type, direction, date, text (transcript / subject + body email), duration_seconds (calls).
    Text trunchiat la 600 caractere per interacțiune pentru a limita tokenii.
    """
    cutoff = now - timedelta(days=_WINDOW_DAYS)
    out = []
    try:
        # Apeluri — transcript real
        cur.execute(
            """
            SELECT started_at, direction, duration_seconds,
                   LEFT(transcript, 600) AS transcript_text
            FROM calls
            WHERE client_id = %s AND started_at >= %s
              AND transcript IS NOT NULL AND transcript <> ''
            ORDER BY started_at DESC
            LIMIT %s
            """,
            (client_id, cutoff, limit),
        )
        for row in cur.fetchall():
            (started, direction, dur, text) = _row_get(row, "started_at", "direction", "duration_seconds", "transcript_text")
            direction = direction or "inbound"
            dur = dur or 0
            text = text or ""
            if text and str(text).strip():
                out.append({
                    "type": "apel",
                    "direction": str(direction),
                    "date": str(started)[:10] if started else "",
                    "duration_sec": int(dur),
                    "text": str(text).strip(),
                })
    except Exception:
        logger.warning("satisfaction_engine: _collect_raw_interactions calls eroare client_id=%s", client_id, exc_info=True)

    try:
        # Emailuri — subject + body_text (toate inbound — tabela emails conține doar mesajele primite)
        cur.execute(
            """
            SELECT received_at, subject,
                   LEFT(body_text, 400) AS body_preview
            FROM emails
            WHERE client_id = %s AND received_at >= %s
              AND (body_text IS NOT NULL AND body_text <> '' OR subject IS NOT NULL AND subject <> '')
            ORDER BY received_at DESC
            LIMIT %s
            """,
            (client_id, cutoff, limit),
        )
        for row in cur.fetchall():
            (received, subject, body) = _row_get(row, "received_at", "subject", "body_preview")
            subject = subject or ""
            body = body or ""
            text = (f"Subiect: {subject}\n{body}").strip() if subject else str(body).strip()
            if text:
                out.append({
                    "type": "email",
                    "direction": "inbound",
                    "date": str(received)[:10] if received else "",
                    "text": text,
                })
    except Exception:
        logger.warning("satisfaction_engine: _collect_raw_interactions emails eroare client_id=%s", client_id, exc_info=True)

    # Sortare cronologică descrescătoare
    out.sort(key=lambda x: x.get("date", ""), reverse=True)
    return out[:limit]


def compute_satisfaction_ai(
    client_id: int,
    iris_client_id: Optional[int],
    cur,
    now: datetime,
    *,
    use_ai: bool = True,
    skip_exclude_check: bool = False,
) -> dict:
    """Scor de satisfacție — IRIS citește textul brut și dă scorul direct.

    Fără piloni matematici intermediari. IRIS judecă pe transcrierile reale.
    Fallback la scor neutru (80) dacă IRIS nu e disponibil.
    """
    # Verificare excludere
    if not skip_exclude_check:
        try:
            cur.execute("SELECT satisfaction_exclude FROM clients WHERE id = %s", (client_id,))
            row = cur.fetchone()
            if row and _first(row):
                return {
                    "satisfaction_pct": None,
                    "is_unsatisfied": False,
                    "breakdown": {"scoring_mode": "excluded"},
                    "config_used": {"version": "v3"},
                    "computed_at": now.isoformat(),
                    "error": "excluded",
                }
        except Exception:
            pass

    # Colectare interacțiuni brute
    raw_interactions = _collect_raw_interactions(client_id, cur, now, limit=25)
    n_interactions = len(raw_interactions)

    # Colectare red flags algoritmice (din interaction_analysis) pentru validare IRIS
    try:
        interactions_ia = _fetch_interactions(client_id, cur, now, _WINDOW_DAYS)
        algo_red_flags, _ = _collect_red_flags(interactions_ia, now)
    except Exception:
        algo_red_flags = []

    if n_interactions == 0:
        return {
            "satisfaction_pct": None,
            "is_unsatisfied": False,
            "breakdown": {"scoring_mode": "no_data", "total_interactions": 0},
            "config_used": {"version": "v3"},
            "computed_at": now.isoformat(),
            "error": "no_data",
        }

    # Sub 2 interacțiuni → benefit of the doubt
    if n_interactions < 2:
        breakdown = {
            "scoring_mode": "benefit_of_doubt",
            "total_interactions": n_interactions,
            "segment": "sanatos",
            "red_flags_active": [],
            "iris_reasoning": "Date insuficiente — benefit of the doubt aplicat.",
        }
        return {
            "satisfaction_pct": 100.0,
            "is_unsatisfied": False,
            "breakdown": breakdown,
            "config_used": {"version": "v3"},
            "computed_at": now.isoformat(),
        }

    breakdown = {
        "scoring_mode": "iris_fallback",
        "total_interactions": n_interactions,
        "red_flags_active": algo_red_flags,
        "segment": "sanatos",
        "iris_reasoning": "",
    }

    if not use_ai:
        breakdown["scoring_mode"] = "no_ai"
        ai_pct = 80.0
        breakdown["segment"] = _segment(ai_pct)
        return {
            "satisfaction_pct": ai_pct,
            "is_unsatisfied": ai_pct < 70.0,
            "breakdown": breakdown,
            "config_used": {"version": "v3"},
            "computed_at": now.isoformat(),
        }

    try:
        from app.services import iris_ai
    except Exception:
        iris_ai = None

    if not iris_ai or not iris_ai.is_configured():
        # IRIS indisponibil — scor neutru conservator
        ai_pct = 80.0
        breakdown["segment"] = _segment(ai_pct)
        return {
            "satisfaction_pct": ai_pct,
            "is_unsatisfied": ai_pct < 70.0,
            "breakdown": breakdown,
            "config_used": {"version": "v3"},
            "computed_at": now.isoformat(),
        }

    try:
        context_for_iris = json.dumps({
            "total_interactiuni_90d": n_interactions,
            "red_flags_detectate_algoritmic": algo_red_flags,
            "interactiuni": raw_interactions,
        }, ensure_ascii=False, indent=2)

        iris_resp = iris_ai.run_prompt(
            system=SATISFACTION_SYSTEM,
            content=context_for_iris,
            response_format="json",
            temperature=0.1,
            max_tokens=500,
            client="Cargo360-SatisfactionAI",
            no_cache=True,
        )

        if iris_resp and iris_resp.get("ok"):
            parsed = iris_resp.get("parsed") or {}
            if not isinstance(parsed, dict) and iris_resp.get("text"):
                try:
                    parsed = json.loads(iris_resp["text"])
                except Exception:
                    parsed = {}

            if isinstance(parsed, dict) and "satisfaction_pct" in parsed:
                ai_raw = float(parsed["satisfaction_pct"])
                # +15% boost — IRIS tinde să fie prea drastic; ajustăm în favoarea clientului
                ai_boosted = min(100.0, ai_raw + 15.0)
                # Floor 60% — niciun client activ nu apare sub 60 în dashboard
                ai_pct = round(_clamp(max(60.0, ai_boosted)), 1)

                # Red flags confirmate de IRIS — înlocuiesc detecția algoritmică
                confirmed_flags = parsed.get("red_flags_confirmed")
                result_flags = confirmed_flags if isinstance(confirmed_flags, list) else algo_red_flags
                breakdown["red_flags_active"] = result_flags

                # Segment bazat pe scorul AI + red flags confirmate
                confirmed_set = set(result_flags)
                if confirmed_set & _RED_FLAGS_CRITIC_30D:
                    final_seg = "critic"
                elif confirmed_set & _RED_FLAGS_RISK_60D:
                    final_seg = _segment_min(_segment(ai_pct), "la_risc")
                else:
                    final_seg = _segment(ai_pct)
                breakdown["segment"] = final_seg

                breakdown["iris_reasoning"] = parsed.get("reasoning", "")
                breakdown["scoring_mode"] = "ai"
                return {
                    "satisfaction_pct": ai_pct,
                    "is_unsatisfied": ai_pct < 70.0,
                    "breakdown": breakdown,
                    "config_used": {"version": "v3"},
                    "computed_at": now.isoformat(),
                }
    except Exception:
        logger.warning("satisfaction_engine: compute_satisfaction_ai eroare IRIS client_id=%s", client_id, exc_info=True)

    # Fallback la scor neutru dacă IRIS a eșuat
    ai_pct = 80.0
    breakdown["segment"] = _segment(ai_pct)
    return {
        "satisfaction_pct": ai_pct,
        "is_unsatisfied": ai_pct < 70.0,
        "breakdown": breakdown,
        "config_used": {"version": "v3"},
        "computed_at": now.isoformat(),
    }


# ══════════════════════════════════════════════════════════════════════════════
# MOTOR v4 — traiectorie IRIS (prompt V4, 2026-08)
#
# Un singur KPI: starea finală 0-100 (sau N/A) din promptul de traiectorie V4.
# Fără piloni Emoție/Context/Restituire. Fără boost/floor pe scorul IRIS.
#
# Sursa datelor: cts_ground_truth (mailuri) + cts_calls_ground_truth (apeluri),
#   pe luna calendaristică [month_start, month_end).
# ══════════════════════════════════════════════════════════════════════════════

_TRAJECTORY_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "satisfaction_trajectory_v4.txt"
_TRAJECTORY_SYSTEM_CACHE: Optional[str] = None

# Config legacy (păstrat pentru compatibilitate settings; nu mai ponderăm piloni)
_V4_DEFAULTS = {
    "pen_sesizare": 10.0,
    "pen_reclamatie": 20.0,
    "pen_recontact": 5.0,
    "w_emotion": 0.0,
    "w_context": 1.0,
    "recovery_max": 0.0,
    "mode": "iris_trajectory_v4",
    "prompt_version": "V4",
}


def _load_trajectory_v4_system() -> str:
    global _TRAJECTORY_SYSTEM_CACHE
    if _TRAJECTORY_SYSTEM_CACHE is None:
        _TRAJECTORY_SYSTEM_CACHE = _TRAJECTORY_PROMPT_PATH.read_text(encoding="utf-8")
    return _TRAJECTORY_SYSTEM_CACHE

# Numere interne CargoTrack (nu sunt clienți) — se ignoră la maparea apel→client
_CARGOTRACK_PHONE_PREFIXES = ("037443006",)


def _load_v4_config(cur) -> dict:
    """Citește ponderile/penalitățile din settings key 'satisfaction.v4' (fallback la defaults)."""
    cfg = dict(_V4_DEFAULTS)
    try:
        cur.execute("SELECT value FROM settings WHERE key = %s", ("satisfaction.v4",))
        row = cur.fetchone()
        if row:
            val = _first(row)
            if isinstance(val, str):
                val = json.loads(val)
            if isinstance(val, dict):
                for k in cfg:
                    if k in val and val[k] is not None:
                        if isinstance(cfg[k], str):
                            cfg[k] = str(val[k])
                            continue
                        try:
                            cfg[k] = float(val[k])
                        except (TypeError, ValueError):
                            pass
                # păstrează și chei noi (mode/prompt_version) chiar dacă nu sunt în defaults numerice
                for k in ("mode", "prompt_version", "single_kpi"):
                    if k in val and val[k] is not None:
                        cfg[k] = val[k]
    except Exception:
        logger.warning("satisfaction v4: nu am putut citi settings satisfaction.v4, folosesc defaults", exc_info=True)
    return cfg


def _norm_category(cat) -> str:
    """Normalizează cts_category la {informatie, sesizare, reclamatie}. Gol/necunoscut → informatie."""
    c = (cat or "").strip().lower()
    if c in ("sesizare", "reclamatie"):
        return c
    return "informatie"  # informatie, necunoscut, gol, orice altceva = neutru


def _email_domain(addr: str) -> str:
    a = (addr or "").strip().lower()
    if "@" in a:
        return a.rsplit("@", 1)[-1]
    return ""


def _client_email_domains(cur, client_id: int) -> set:
    """Domeniile de email ale unui client (din clients.emails, jsonb murdar cu ';' multiple)."""
    domains = set()
    try:
        cur.execute("SELECT emails FROM clients WHERE id = %s", (client_id,))
        row = cur.fetchone()
        if not row:
            return domains
        emails = _first(row)
        if isinstance(emails, str):
            try:
                emails = json.loads(emails)
            except Exception:
                emails = [emails]
        if not isinstance(emails, list):
            return domains
        for entry in emails:
            # Fiecare element poate conține mai multe adrese lipite cu ';'
            for part in str(entry).split(";"):
                d = _email_domain(part)
                # Ignoră domenii free-mail generice și domenii interne (nu identifică unic un client)
                _GENERIC_DOMAINS = {
                    "gmail.com", "yahoo.com", "yahoo.ro", "yahoo.es", "yahoo.it", "yahoo.fr",
                    "hotmail.com", "hotmail.ro", "hotmail.it", "hotmail.fr",
                    "outlook.com", "outlook.ro",
                    "icloud.com", "me.com", "mac.com",
                    "mail.ru", "mail.com", "ymail.com",
                    "live.com", "live.ro", "msn.com",
                    "protonmail.com", "proton.me",
                    "cargotrack.ro", "trakosoft.ro",  # domenii interne — nu identifică clientul
                }
                if d and d not in _GENERIC_DOMAINS:
                    domains.add(d)
    except Exception:
        logger.warning("satisfaction v4: _client_email_domains eroare client_id=%s", client_id, exc_info=True)
    return domains


def _client_email_addresses(cur, client_id: int) -> set:
    """Adresele EXACTE ale clientului din clients.emails (jsonb, poate avea ';' multiple).

    Înlocuiește potrivirea pe DOMENIU la legarea mailurilor orfane. Motiv: un domeniu de firmă
    apare frecvent la mai mulți clienți CTS — pe staging, 171 de domenii sunt partajate între 646
    de clienți (ex. `ruptela.com` la 8 clienți, printre care unul cu 0 mailuri proprii). Cu
    potrivire pe domeniu, fiecare dintre ei primea mailurile tuturor celorlalți, de unde
    „am analizat 54 de interacțiuni" pentru un client care are 10.

    Adresa exactă e la fel de bună ca sursă de legare, fără contaminare între clienți.
    """
    addresses = set()
    try:
        # Doar adresele care identifica UNIC clientul, din tabela derivata `client_unique_emails`
        # (vezi migratia 20260729h). In CTS multe adrese sunt puse pe mai multi clienti: furnizori
        # (`support@ruptela.com` la 8), banci (`no-reply@unicredit.ro` la 6), sau text liber in loc
        # de adresa (`dispecer` la 37, `sotia` la 27) — o adresa partajata nu identifica pe nimeni.
        cur.execute(
            "SELECT email FROM client_unique_emails WHERE client_id = %s",
            (client_id,),
        )
        for row in cur.fetchall():
            a = _first(row)
            if a:
                addresses.add(str(a))
    except Exception:
        logger.warning("satisfaction v4: _client_email_addresses eroare client_id=%s",
                       client_id, exc_info=True)
    return addresses


def _fetch_month_interactions(client_id: int, cur, start: datetime, end: datetime) -> Tuple[List[dict], List[dict]]:
    """Interacțiunile clientului DIN LUNĂ (calendaristic), din CTS ground-truth.

    Returnează (received, sent):
      received = mailuri+apeluri PRIMITE de la client (folosite pentru penalizări + IRIS)
      sent     = mailuri trimise de agent (context pentru restituire — 'agentul a răspuns rezolvat')

    Legare mail↔client: emails.client_id SAU adresa expeditorului ∈ adresele EXACTE ale clientului
      (nu pe domeniu — domeniile partajate contaminau clienții între ei; vezi
      `_client_email_addresses`).
    Legare apel↔client: calls.client_id SAU phone_match pe numărul non-CargoTrack.
    """
    received: List[dict] = []
    sent: List[dict] = []
    addresses = _client_email_addresses(cur, client_id)

    # ── Mailuri primite (received) ────────────────────────────────────────────
    # Prinde mailurile cu client_id setat + orfanele de la o adresă declarată a clientului.
    try:
        addr_list = list(addresses)
        cur.execute(
            """
            SELECT * FROM (
                SELECT e.id, gt.cts_category, gt.cts_thread_key, e.subject,
                       e.body_text, e.body_html, e.received_at,
                       gt.cts_solved_at, gt.cts_reply_at, e.from_address
                FROM cts_ground_truth gt
                JOIN emails e ON e.id = gt.email_id
                WHERE COALESCE(gt.cts_direction, 'received') = 'received'
                  AND e.received_at >= %s AND e.received_at < %s
                  AND (
                        e.client_id = %s
                     OR (e.client_id IS NULL AND %s <> '{}'::text[]
                         AND LOWER(TRIM(e.from_address)) = ANY(%s))
                  )
                ORDER BY e.received_at DESC
                LIMIT 300
            ) sub
            ORDER BY received_at ASC
            """,
            (start, end, client_id, addr_list, addr_list),
        )
        for row in cur.fetchall():
            (eid, cat, thread, subject, body_text, body_html, received_at, solved_at, reply_at, from_addr) = _row_get(
                row, "id", "cts_category", "cts_thread_key", "subject", "body_text", "body_html",
                "received_at", "cts_solved_at", "cts_reply_at", "from_address"
            )
            # Doar mesajul NOU (ultimul reply), fara istoricul citat din thread — altfel un thread
            # lung (Re:Re:Re...) contamineaza analiza AI cu texte VECHI, iar un singur follow-up
            # scurt/neutru ("multumesc", "am inteles") e etichetat gresit drept "revenire pe
            # problema nerezolvata" doar pentru ca body-ul brut contine si plangerea veche citata.
            body = _email_body({"body_text": body_text, "body_html": body_html})[:600]
            received.append({
                "kind": "email",
                "ref": f"mail#{eid}",
                "category": _norm_category(cat),
                "thread_key": thread or "",
                "subject": subject or "",
                "text": (str(body or "")).strip(),
                "date": str(received_at)[:19] if received_at else "",
                "occurred_at": received_at,
                "solved_at": str(solved_at)[:19] if solved_at else None,
                "reply_at": str(reply_at)[:19] if reply_at else None,
            })
    except Exception:
        logger.warning("satisfaction v4: fetch mailuri received eroare client_id=%s", client_id, exc_info=True)

    # ── Mailuri trimise de agent (sent) — context restituire ────────────────────
    try:
        addr_list = list(addresses)
        cur.execute(
            """
            SELECT e.id, gt.cts_thread_key, e.subject,
                   LEFT(COALESCE(gt.cts_reply_text, ''), 500) AS reply_preview,
                   COALESCE(gt.cts_reply_at, e.received_at) AS sent_at
            FROM cts_ground_truth gt
            JOIN emails e ON e.id = gt.email_id
            WHERE gt.cts_direction = 'sent'
              AND COALESCE(gt.cts_reply_at, e.received_at) >= %s
              AND COALESCE(gt.cts_reply_at, e.received_at) < %s
              AND (
                    e.client_id = %s
                 OR (e.client_id IS NULL AND %s <> '{}'::text[]
                     AND EXISTS (
                         SELECT 1 FROM jsonb_array_elements_text(COALESCE(e.to_addresses, '[]'::jsonb)) AS addr
                         WHERE LOWER(TRIM(addr)) = ANY(%s)
                     ))
              )
            ORDER BY sent_at ASC
            LIMIT 150
            """,
            (start, end, client_id, addr_list, addr_list),
        )
        for row in cur.fetchall():
            (eid, thread, subject, reply, sent_at) = _row_get(
                row, "id", "cts_thread_key", "subject", "reply_preview", "sent_at"
            )
            txt = (str(reply or "")).strip()
            if not txt:
                continue
            sent.append({
                "kind": "email_agent",
                "ref": f"reply#{eid}",
                "thread_key": thread or "",
                "subject": subject or "",
                "text": txt,
                "date": str(sent_at)[:19] if sent_at else "",
            })
    except Exception:
        logger.warning("satisfaction v4: fetch mailuri sent eroare client_id=%s", client_id, exc_info=True)

    # ── Apeluri (received = orice apel al clientului; direcția e informativă) ────
    try:
        cur.execute(
            """
            -- DISTINCT ON (c.id): un apel poate avea MAI MULTE rânduri în
            -- cts_calls_ground_truth (6 cazuri pe staging), iar LEFT JOIN-ul îl returna o dată
            -- per rând → apelul se număra dublu în interacțiunile analizate.
            SELECT DISTINCT ON (c.id)
                   c.id, gt.cts_category, c.direction, c.started_at,
                   LEFT(c.transcript, 600) AS transcript_preview,
                   c.caller_number, c.callee_number, c.client_id
            FROM calls c
            LEFT JOIN cts_calls_ground_truth gt ON gt.call_local_id = c.id
            WHERE c.started_at >= %s AND c.started_at < %s
              AND c.client_id = %s
            ORDER BY c.id, gt.cts_category NULLS LAST
            LIMIT 150
            """,
            (start, end, client_id),
        )
        call_rows = cur.fetchall()
    except Exception:
        call_rows = []
        logger.warning("satisfaction v4: fetch apeluri eroare client_id=%s", client_id, exc_info=True)

    # Apeluri orfane (client_id NULL) — mapare prin telefon
    orphan_calls = _fetch_orphan_calls_for_client(client_id, cur, start, end)

    for row in list(call_rows):
        (cid, cat, direction, started_at, transcript, caller, callee, c_client) = _row_get(
            row, "id", "cts_category", "direction", "started_at", "transcript_preview",
            "caller_number", "callee_number", "client_id"
        )
        received.append({
            "kind": "call",
            "ref": f"apel#{cid}",
            "category": _norm_category(cat),
            "thread_key": "",  # apelurile nu au thread
            "subject": "",
            "text": (str(transcript or "")).strip(),
            "date": str(started_at)[:19] if started_at else "",
            "occurred_at": started_at,
            "direction": direction or "",
        })
    received.extend(orphan_calls)

    # Sortare cronologică (mai vechi → mai nou) — util pentru IRIS să vadă evoluția
    received.sort(key=lambda x: str(x.get("date") or ""))
    sent.sort(key=lambda x: str(x.get("date") or ""))
    return received, sent


def _fetch_orphan_calls_for_client(client_id: int, cur, start: datetime, end: datetime) -> List[dict]:
    """Apeluri cu client_id NULL a căror număr non-CargoTrack se mapează pe acest client (phone_match)."""
    out: List[dict] = []
    try:
        from app.services import phone_match
    except Exception:
        return out
    # Numerele de telefon ale clientului (clients.phones)
    client_phones = set()
    try:
        cur.execute("SELECT phones FROM clients WHERE id = %s", (client_id,))
        row = cur.fetchone()
        phones = _first(row) if row else None
        if isinstance(phones, str):
            try:
                phones = json.loads(phones)
            except Exception:
                phones = []
        if isinstance(phones, list):
            for p in phones:
                n = phone_match.normalize_phone(str(p))
                if n:
                    client_phones.add(n)
    except Exception:
        pass
    if not client_phones:
        return out
    try:
        cur.execute(
            """
            -- DISTINCT ON (c.id): un apel poate avea mai multe rânduri CTS legate (vezi
            -- comentariul din _fetch_month_interactions) — altfel se numără dublu.
            SELECT DISTINCT ON (c.id)
                   c.id, gt.cts_category, c.direction, c.started_at,
                   LEFT(c.transcript, 600) AS transcript_preview,
                   c.caller_number, c.callee_number
            FROM calls c
            LEFT JOIN cts_calls_ground_truth gt ON gt.call_local_id = c.id
            WHERE c.started_at >= %s AND c.started_at < %s
              AND c.client_id IS NULL
            ORDER BY c.id, gt.cts_category NULLS LAST
            LIMIT 300
            """,
            (start, end),
        )
        for row in cur.fetchall():
            (cid, cat, direction, started_at, transcript, caller, callee) = _row_get(
                row, "id", "cts_category", "direction", "started_at", "transcript_preview",
                "caller_number", "callee_number"
            )
            # Numărul clientului = celălalt capăt față de CargoTrack
            candidates = []
            for num in (caller, callee):
                n = phone_match.normalize_phone(str(num or ""))
                if not n:
                    continue
                if any(n.lstrip("+").startswith(pfx) for pfx in _CARGOTRACK_PHONE_PREFIXES):
                    continue  # număr intern CargoTrack
                candidates.append(n)
            if not any(n in client_phones for n in candidates):
                continue
            out.append({
                "kind": "call",
                "ref": f"apel#{cid}",
                "category": _norm_category(cat),
                "thread_key": "",
                "subject": "",
                "text": (str(transcript or "")).strip(),
                "date": str(started_at)[:19] if started_at else "",
                "occurred_at": started_at,
                "direction": direction or "",
            })
    except Exception:
        logger.warning("satisfaction v4: orphan calls eroare client_id=%s", client_id, exc_info=True)
    return out


def _pillar_emotion_v4(received: List[dict], cfg: dict) -> Tuple[float, dict]:
    """KPI Emoție determinist: 100 - Σ penalizări categorie (clamp 0). Revenirile se aplică ulterior."""
    n_ses = sum(1 for i in received if i.get("category") == "sesizare")
    n_rec = sum(1 for i in received if i.get("category") == "reclamatie")
    n_info = sum(1 for i in received if i.get("category") == "informatie")
    pen_cat = n_ses * cfg["pen_sesizare"] + n_rec * cfg["pen_reclamatie"]
    score = _clamp(100.0 - pen_cat)
    return score, {
        "n_sesizari": n_ses,
        "n_reclamatii": n_rec,
        "n_informatie": n_info,
        "penalties_category": round(pen_cat, 1),
    }


# ── Prompturi IRIS v4 ──────────────────────────────────────────────────────────

_V4_RECONTACT_SYSTEM = """Ești analist de relații clienți B2B în servicii logistice/fleet management.
Primești TOATE mesajele PRIMITE de la un client într-o lună (mailuri + apeluri, cu thread/subiect/categorie CTS).
Sarcina: numără mesajele în care clientul REVINE pe o problemă care fusese deja semnalată ca sesizare/reclamație.

CONDIȚIE OBLIGATORIE (verifică ÎNTÂI, altfel NU se numără):
- Trebuie să existe, în ACELAȘI thread (sau clar aceeași temă), un mesaj ANTERIOR din lună categorisit
  "sesizare" sau "reclamatie". Revenirea se numără DOAR dacă un asemenea precedent există.
- Un mesaj de tip "informatie" care doar menționează o problemă trecută, dar NU are niciun mesaj anterior
  cu categoria sesizare/reclamatie în același thread, NU este revenire — indiferent cât de frustrat sună.

CE SE NUMĂRĂ (fiecare astfel de mesaj = o revenire, ȘI îndeplinește condiția de mai sus):
- Clientul spune clar că a mai scris/sunat și încă așteaptă: „revin", „am mai trimis", „am sunat de 2 ori",
  „încă nu s-a rezolvat", „v-au contactat și nu ați răspuns", „de la data X aștept".
- Insistență explicită pe ACEEAȘI problemă nerezolvată (același subiect/thread ca sesizarea/reclamația anterioară).

CE NU SE NUMĂRĂ (foarte important):
- Mesaje fără niciun precedent sesizare/reclamație în thread — chiar dacă tonul e insistent sau repetitiv.
- Mai multe mesaje cu ÎNTREBĂRI DIFERITE sau solicitări noi (10 reply-uri ≠ problemă persistentă).
- Un follow-up neutru („aveți un update?") fără semnalarea explicită că problema persistă și nemulțumire.
- Mesaje de tip informație fără precedent — întrebări generale, solicitări de documente, actualizări de status.

Fii STRICT: dacă nu există precedent sesizare/reclamație în thread SAU nu e o semnalare EXPLICITĂ de
revenire-pe-nerezolvat, NU o număra.

Returnează STRICT JSON:
{
  "recontacts": [{"ref": "<ref-ul mesajului, ex mail#49604>", "precedent_ref": "<ref-ul mesajului anterior sesizare/reclamatie din același thread>", "reason": "<citat scurt din text>"}],
  "count": <număr întreg = len(recontacts)>
}"""

_V4_CONTEXT_SYSTEM = """Ești analist senior de satisfacție clienți B2B (15 ani în logistică/fleet management).
Primești TOATE interacțiunile unui client dintr-o lună (mailuri + apeluri, primite ȘI răspunsurile agenților).
Dă un scor holistic de satisfacție 0-100 pe baza ANSAMBLULUI, ca o interpretare umană.

CUM JUDECI:
- Probleme semnalate DAR rezolvate + client care mulțumește/apreciază → scor mare.
- Doar întrebări, nelămuriri, solicitări de tip „informație", fără nicio remarcă negativă → scor MARE.
  (E complet normal ca un client B2B activ să pună întrebări operaționale. NU e nemulțumire.)
- Probleme reale nerezolvate, client care revine frustrat pe aceeași temă → scor MIC.
- Amenințări de plecare, reziliere, mențiune concurență ca alternativă reală → scor foarte mic.

REALISM (obligatoriu):
- NU da 100 automat — păstrează 100 doar pentru o lună complet senină, cu semnale pozitive clare.
- NU fi exagerat de sever: 2-3 mailuri cu întrebări fără nimic negativ NU merită sub ~85.
  Un client care doar întreabă lucruri și nu se plânge de nimic e un client OK, nu unul la 60%.
- Distinge un incident tehnic punctual (normal) de nemulțumire reală față de SERVICIU.

NU menționa "B2B" în reasoning — TOȚI clienții sunt B2B, e implicit, nu o etichetă distinctivă.

Returnează STRICT JSON:
{
  "context_pct": <float 0-100, 1 zecimală>,
  "reasoning": <2-3 propoziții CONCRETE în română, cu exemple reale din mesaje, FĂRĂ eticheta "B2B">,
  "dominant_signal": <string scurt: semnalul dominant al lunii>,
  "trend_assessment": <string scurt: în ameliorare / stabil / în deteriorare>
}"""

_V4_RECOVERY_SYSTEM = """Ești analist de satisfacție clienți. Un client a acumulat penalizări într-o lună
(din sesizări/reclamații/reveniri). Sarcina: decide ce PROCENT din penalizări poate fi RESTITUIT, pe baza
dovezilor că problemele au fost REZOLVATE și clientul s-a arătat MULȚUMIT.

CÂND SE RESTITUIE (dovadă în text):
- Agentul revine la client și confirmă rezolvarea, iar clientul mulțumește/apreciază ÎN MAX 48 DE ORE.
- Clientul spune explicit că problema (o sesizare/reclamație reală) s-a rezolvat și e mulțumit/recunoscător.
- Apreciere clară a promptitudinii într-un context de PROBLEMĂ reală rezolvată.

CÂND NU SE RESTITUIE (gardă anti-abuz — STRICT):
- Mulțumire la o simplă ÎNTREBARE de tip informație („unde e butonul X?" → „mulțumesc pentru promptitudine").
  Asta NU e rezolvarea unei sesizări/reclamații → NU restitui.
- Mulțumire de politețe fără legătură cu o problemă reală rezolvată.
- Mulțumire care vine la MAI MULT de 48h după rezolvare, sau pe altă temă.

Restituie proporțional cu cât de mult din nemulțumire a fost efectiv reparat. Maxim 50% (0.50).

Returnează STRICT JSON:
{
  "recovery_pct": <float 0.0-0.50>,
  "reasoning": <1-2 propoziții în română, cu dovada concretă din text>
}"""


def _salvage_satisfaction_json(text: str) -> Optional[dict]:
    """Recuperează câmpurile esențiale din JSON IRIS trunchiat (max_tokens)."""
    import re
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```\s*$", "", t)
    try:
        obj = json.loads(t)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass

    # Închide array/obiecte trunchiate: taie la ultimul obiect complet din trajectory_events
    cut = t
    # încearcă să închidă JSON-ul după ultimul `},` complet din events
    idx = cut.rfind("},\n")
    if idx < 0:
        idx = cut.rfind("},")
    if idx > 0 and '"trajectory_events"' in cut[:idx]:
        candidate = cut[: idx + 1] + "], \"reputation_risks\": [], \"escalation_risks\": [], \"financial_risk\": null, \"reasoning\": null, \"suggestions\": []}"
        # dacă reasoning există deja mai sus, ok; altfel null
        try:
            # balanță acolade brute
            opens = candidate.count("{") - candidate.count("}")
            if opens > 0:
                candidate += "}" * opens
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass

    out: Dict[str, Any] = {}
    m = re.search(r'"satisfaction_pct"\s*:\s*(null|-?\d+(?:\.\d+)?)', t)
    if m:
        out["satisfaction_pct"] = None if m.group(1) == "null" else float(m.group(1))

    def _str_field(name: str) -> Optional[str]:
        mm = re.search(rf'"{name}"\s*:\s*"((?:\\.|[^"\\])*)"', t)
        if not mm:
            return None
        try:
            return json.loads('"' + mm.group(1) + '"')
        except Exception:
            return mm.group(1)

    for key in ("no_score_label", "no_score_note", "category", "trajectory_shape", "reasoning"):
        val = _str_field(key)
        if val is not None:
            out[key] = val
    # dacă reasoning lipsește, folosește no_score_note
    if not out.get("reasoning") and out.get("no_score_note"):
        out["reasoning"] = out["no_score_note"]
    out.setdefault("trajectory_events", [])
    out.setdefault("reputation_risks", [])
    out.setdefault("escalation_risks", [])
    out.setdefault("suggestions", [])
    if any(k in out for k in ("satisfaction_pct", "no_score_label", "reasoning", "category")):
        out["_salvaged"] = True
        return out
    return None


def _iris_call(system: str, payload: dict, max_tokens: int = 500) -> Optional[dict]:
    """Apel IRIS cu JSON. Returnează dict-ul parsat sau None dacă IRIS indisponibil/eșec.

    Dacă gateway-ul întoarce JSON_PARSE_ERROR pe răspuns trunchiat (max_tokens),
    încearcă recuperarea câmpurilor esențiale din raw_text.
    """
    try:
        from app.services import iris_ai
    except Exception:
        return None
    if not iris_ai or not iris_ai.is_configured():
        return None
    try:
        content = json.dumps(payload, ensure_ascii=False, indent=2)
        resp = iris_ai.run_prompt(
            system=system,
            content=content,
            response_format="json",
            temperature=0.1,
            max_tokens=max_tokens,
            client="Cargo360-SatisfactionV4",
            no_cache=True,
            task="satisfaction_v4_trajectory",
        )
        if resp and resp.get("ok"):
            parsed = resp.get("parsed")
            if not isinstance(parsed, dict) and resp.get("text"):
                parsed = _salvage_satisfaction_json(resp.get("text") or "")
            return parsed if isinstance(parsed, dict) else None

        # eșec oficial — încearcă salvage din raw_text (caz tipic: output tăiat la max_tokens)
        err = (resp or {}).get("error") or {}
        raw = err.get("raw_text") or (resp or {}).get("text") or ""
        salvaged = _salvage_satisfaction_json(raw)
        if salvaged:
            logger.warning(
                "satisfaction v4: JSON IRIS invalid/trunchiat — recuperat câmpuri esențiale (code=%s keys=%s)",
                err.get("code"),
                sorted(k for k in salvaged.keys() if not k.startswith("_")),
            )
            return salvaged
        if err:
            logger.warning(
                "satisfaction v4: apel IRIS eșuat code=%s msg=%s",
                err.get("code"),
                str(err.get("message") or "")[:200],
            )
    except Exception:
        logger.warning("satisfaction v4: apel IRIS eșuat", exc_info=True)
    return None


def _iris_payload_interactions(received: List[dict], sent: List[dict] = None, *, text_limit: int = 600) -> list:
    """Serializează interacțiunile pentru IRIS (câmpuri relevante, text trunchiat)."""
    out = []
    for i in received:
        out.append({
            "ref": i.get("ref"),
            "tip": i.get("kind"),
            "categorie": i.get("category"),
            "subiect": i.get("subject") or None,
            "thread": i.get("thread_key") or None,
            "data": i.get("date"),
            "text": (i.get("text") or "")[:text_limit],
        })
    if sent:
        sent_limit = max(500, text_limit - 100)
        for s in sent:
            out.append({
                "ref": s.get("ref"),
                "tip": "raspuns_agent",
                "subiect": s.get("subject") or None,
                "thread": s.get("thread_key") or None,
                "data": s.get("date"),
                "text": (s.get("text") or "")[:sent_limit],
            })
    return out


def compute_satisfaction_v4(
    client_id: int,
    iris_client_id: Optional[int],
    cur,
    month_start: datetime,
    month_end: datetime,
    *,
    use_ai: bool = True,
    skip_exclude_check: bool = False,
) -> dict:
    """Scor satisfacție v4 — 1 apel IRIS per săptămână cu interacțiuni; luna = medie.

    Nu există apel IRIS separat pe lună. Scorul lunar = medie ponderată a scorurilor
    săptămânale cu greutatea = nr. interacțiuni din săptămână (echivalent cu media pe
    interacțiuni dacă fiecare moștenește scorul săptămânii sale).
    """
    import time as _time
    import re

    now = month_end
    cfg = _load_v4_config(cur)
    config_used = {
        "version": "v4_trajectory",
        "prompt_version": "V4",
        "weights": cfg,
        "granularity": "week_iris_month_avg",
        "no_cache": True,
    }

    if not skip_exclude_check:
        try:
            cur.execute("SELECT satisfaction_exclude FROM clients WHERE id = %s", (client_id,))
            row = cur.fetchone()
            if row and _first(row):
                return {
                    "satisfaction_pct": None,
                    "is_unsatisfied": False,
                    "breakdown": {"scoring_mode": "excluded"},
                    "config_used": config_used,
                    "computed_at": now.isoformat(),
                    "error": "excluded",
                }
        except Exception:
            pass

    received, sent = _fetch_month_interactions(client_id, cur, month_start, month_end)
    n = len(received) + len(sent)

    def _na_result(label: str, note: str, *, interactions: int, extra: Optional[dict] = None) -> dict:
        breakdown = {
            "scoring_mode": "v4_trajectory_na",
            "store_null": True,
            "single_kpi": "iris_stare_finala",
            "total_interactions": interactions,
            "segment": "neutru",
            "red_flags_active": [],
            "no_score_label": label,
            "no_score_note": note,
            "iris_reasoning": note,
            "category": label,
            "trajectory_shape": None,
            "trajectory_events": [],
            "weekly_trajectories": [],
            "reputation_risks": [],
            "escalation_risks": [],
            "financial_risk": None,
            "suggestions": [],
            "iris_calls": 0,
            "month_aggregation": "weighted_avg_weeks",
        }
        if extra:
            breakdown.update(extra)
        return {
            "satisfaction_pct": None,
            "is_unsatisfied": False,
            "breakdown": breakdown,
            "config_used": config_used,
            "computed_at": now.isoformat(),
        }

    if n == 0:
        return _na_result(
            "Neutru — fără interacțiune (necesită contact proactiv)",
            "De ce N/A: nicio interacțiune (apel/email) în luna analizată. "
            "Ce se știe: fără semnal pe axa de serviciu sau financiară în fereastra curentă. "
            "Recomandare: contact proactiv sau extinderea ferestrei pentru semnal real.",
            interactions=0,
        )

    if not use_ai:
        return {
            "satisfaction_pct": 75.0,
            "is_unsatisfied": False,
            "breakdown": {
                "scoring_mode": "v4_trajectory_no_ai",
                "single_kpi": "iris_stare_finala",
                "total_interactions": n,
                "segment": "sanatos",
                "iris_reasoning": "AI dezactivat — scor neutru 75.",
                "weekly_trajectories": [],
                "trajectory_events": [],
                "iris_calls": 0,
                "month_aggregation": "weighted_avg_weeks",
            },
            "config_used": config_used,
            "computed_at": now.isoformat(),
        }

    def _item_dt(item: dict) -> Optional[datetime]:
        raw = item.get("occurred_at") or item.get("date")
        if raw is None:
            return None
        if isinstance(raw, datetime):
            return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
        s = str(raw).strip()
        if not s:
            return None
        try:
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s[:19] if "T" in s[:19] or len(s) >= 19 else s[:10])
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            try:
                return datetime.strptime(s[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except Exception:
                return None

    def _week_key(dt: datetime) -> str:
        iso = dt.astimezone(timezone.utc).isocalendar()
        return f"{iso.year}-W{iso.week:02d}"

    def _week_bounds(dt: datetime) -> Tuple[datetime, datetime]:
        d = dt.astimezone(timezone.utc)
        monday = (d - timedelta(days=d.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        return monday, monday + timedelta(days=7)

    def _parse_pct(v) -> Optional[float]:
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return round(_clamp(float(v)), 1)
        s = str(v).strip().replace(",", ".")
        if s.lower() in ("", "null", "none", "n/a", "na"):
            return None
        m = re.search(r"-?\d+(?:\.\d+)?", s)
        if not m:
            return None
        try:
            return round(_clamp(float(m.group(0))), 1)
        except ValueError:
            return None

    # Bucket pe săptămâni ISO (doar cele cu interacțiuni)
    buckets: Dict[str, dict] = {}
    order: List[str] = []
    ms = month_start if month_start.tzinfo else month_start.replace(tzinfo=timezone.utc)
    me = month_end if month_end.tzinfo else month_end.replace(tzinfo=timezone.utc)
    for kind, items in (("received", received), ("sent", sent)):
        for it in items:
            dt = _item_dt(it) or ms
            wk = _week_key(dt)
            if wk not in buckets:
                w0, w1 = _week_bounds(dt)
                buckets[wk] = {
                    "week_key": wk,
                    "start": max(w0, ms),
                    "end": min(w1, me),
                    "received": [],
                    "sent": [],
                }
                order.append(wk)
            buckets[wk][kind].append(it)

    weekly_rows: List[dict] = []
    merged_events: List[dict] = []
    iris_calls = 0
    all_rep: List = []
    all_esc: List = []
    all_sug: List = []
    last_fin = None

    for i, wk in enumerate(order):
        wb = buckets[wk]
        w_recv, w_sent = wb["received"], wb["sent"]
        n_w = len(w_recv) + len(w_sent)
        if n_w == 0:
            continue
        period = {
            "week_key": wk,
            "week_start": wb["start"].date().isoformat(),
            "week_end_exclusive": wb["end"].date().isoformat(),
        }
        payload = {
            "perioada": period,
            "nivel_analiza": "saptamana",
            "instructiune": (
                "Analizează traiectoria de satisfacție DOAR pentru această SĂPTĂMÂNĂ (prompt V4). "
                "Interacțiunile = [TRANSCRIEREA CONVERSAȚIEI]. Fără cache. "
                "JSON COMPACT: trajectory_events maxim 10 (explanation ≤1 propoziție); "
                "satisfaction_pct = starea finală a săptămânii."
            ),
            "total_interactiuni": n_w,
            "interactiuni": _iris_payload_interactions(w_recv, w_sent, text_limit=1400),
        }
        parsed = _iris_call(_load_trajectory_v4_system(), payload, max_tokens=5000)
        iris_calls += 1
        if not parsed:
            row = {
                "week_key": wk,
                "week_start": period["week_start"],
                "week_end_exclusive": period["week_end_exclusive"],
                "n_interactions": n_w,
                "satisfaction_pct": None,
                "category": "IRIS eșuat pe săptămână",
                "trajectory_shape": None,
                "iris_reasoning": "Apel IRIS eșuat pentru această săptămână.",
                "no_score_label": "IRIS eșuat",
                "trajectory_events": [],
                "iris_ok": False,
            }
        else:
            pct_w = _parse_pct(parsed.get("satisfaction_pct"))
            events = parsed.get("trajectory_events") if isinstance(parsed.get("trajectory_events"), list) else []
            for ev in events:
                if isinstance(ev, dict):
                    ev = dict(ev)
                    ev["week_key"] = wk
                    merged_events.append(ev)
            reasoning = parsed.get("reasoning") or parsed.get("no_score_note") or ""
            row = {
                "week_key": wk,
                "week_start": period["week_start"],
                "week_end_exclusive": period["week_end_exclusive"],
                "n_interactions": n_w,
                "satisfaction_pct": pct_w,
                "category": parsed.get("category") or parsed.get("no_score_label"),
                "trajectory_shape": parsed.get("trajectory_shape"),
                "iris_reasoning": reasoning,
                "no_score_label": parsed.get("no_score_label"),
                "trajectory_events": events[:20],
                "iris_ok": True,
            }
            if isinstance(parsed.get("reputation_risks"), list):
                all_rep.extend(parsed["reputation_risks"][:5])
            if isinstance(parsed.get("escalation_risks"), list):
                all_esc.extend(parsed["escalation_risks"][:5])
            if isinstance(parsed.get("suggestions"), list):
                all_sug.extend(parsed["suggestions"][:3])
            if isinstance(parsed.get("financial_risk"), dict):
                last_fin = parsed["financial_risk"]
        weekly_rows.append(row)
        if i < len(order) - 1:
            _time.sleep(0.25)

    # Luna = medie ponderată pe interacțiuni (fără apel IRIS lunar)
    scored = [(r["satisfaction_pct"], r["n_interactions"]) for r in weekly_rows if r.get("satisfaction_pct") is not None]
    if not scored:
        # toate săptămânile N/A / eșec
        notes = [r.get("iris_reasoning") or r.get("no_score_label") or "" for r in weekly_rows]
        note = " ".join(x for x in notes if x)[:800] or "Nicio săptămână nu a produs scor IRIS."
        return _na_result(
            "Semnal insuficient pentru un scor de satisfacție",
            note,
            interactions=n,
            extra={
                "weekly_trajectories": weekly_rows,
                "trajectory_events": merged_events[:80],
                "iris_calls": iris_calls,
                "reputation_risks": all_rep[:15],
                "escalation_risks": all_esc[:15],
                "financial_risk": last_fin,
                "suggestions": all_sug[:10],
            },
        )

    weight_sum = sum(w for _, w in scored) or 1
    month_pct = round(_clamp(sum(p * w for p, w in scored) / weight_sum), 1)

    # raționament agregat (nu IRIS lunar)
    parts = []
    for r in weekly_rows:
        if r.get("satisfaction_pct") is None:
            continue
        parts.append(
            f"{r['week_key']}: {r['satisfaction_pct']}% ({r['n_interactions']} interacțiuni)"
            + (f" — {(r.get('iris_reasoning') or '')[:160]}" if r.get("iris_reasoning") else "")
        )
    reasoning = (
        f"Scor lunar = medie ponderată pe interacțiuni din scorurile săptămânale IRIS "
        f"({month_pct}%; {len(scored)} săptămâni scorate, {weight_sum} interacțiuni). "
        + " | ".join(parts)
    )[:1200]

    # categorie din scorul mediu
    if month_pct >= 90:
        category = "Ambasador"
    elif month_pct >= 75:
        category = "Foarte satisfăcut"
    elif month_pct >= 60:
        category = "Satisfăcut"
    elif month_pct >= 45:
        category = "Neutru / satisfacție moderată — recomandat follow-up"
    elif month_pct >= 30:
        category = "Nemulțumit — necesită intervenție"
    else:
        category = "Critic / risc de pierdere a clientului"

    shapes = [r.get("trajectory_shape") for r in weekly_rows if r.get("trajectory_shape")]
    shape = shapes[-1] if shapes else "Agregat săptămânal"

    segment = _segment(month_pct)
    breakdown = {
        "scoring_mode": "v4_trajectory",
        "single_kpi": "iris_stare_finala",
        "total_interactions": n,
        "segment": segment,
        "red_flags_active": [],
        "iris_reasoning": reasoning,
        "category": category,
        "trajectory_shape": shape,
        "trajectory_events": merged_events[:80],
        "weekly_trajectories": weekly_rows,
        "no_score_label": None,
        "no_score_note": None,
        "reputation_risks": all_rep[:15],
        "escalation_risks": all_esc[:15],
        "financial_risk": last_fin,
        "suggestions": all_sug[:10],
        "iris_calls": iris_calls,
        "month_aggregation": "weighted_avg_weeks",
        "month_avg_detail": {
            "weeks_scored": len(scored),
            "weight_interactions": weight_sum,
            "formula": "sum(week_pct * n_interactions) / sum(n_interactions)",
        },
        "iris_holistic": {
            "reasoning": reasoning,
            "dominant_signal": category,
            "trend_assessment": shape or "",
        },
    }
    return {
        "satisfaction_pct": month_pct,
        "is_unsatisfied": month_pct < 70.0,
        "breakdown": breakdown,
        "config_used": config_used,
        "computed_at": now.isoformat(),
    }
