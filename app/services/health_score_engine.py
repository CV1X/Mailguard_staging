"""Customer Health Score v2 — Nivelul 2: Agregare per client.

Citește din `interaction_analysis` (produs de interaction_analyzer.py) și calculează
un scor de sănătate 0–100 pe 4 piloni, salvat în `client_health_score` și
`client_health_history`.

Arhitectură:
  Nivelul 1 (interaction_analyzer.py) → per interacțiune
  Nivelul 2 (acest fișier)            → per client (4 piloni + override-uri)
  Nivelul 3                           → ranking, segmente, alerte (în API/UI)

Piloni:
  emotion      30%  — sentiment agregat cu decay + intensitate emoțională
  effort       25%  — is_repeat_issue, effort_signals, resolution_signal
  operational  25%  — taskuri firefighting/overdue, promisiuni expirate
  relationship 20%  — warmth/formality vs baseline, future_orientation, dezangajare

Utilizare:
  from app.services.health_score_engine import compute_health_score, batch_compute

  result = compute_health_score(client_id, cur, conn)
  # result: {score, segment, pillar_scores, confidence, red_flags_active, override_reason, ...}
"""

import json
import logging
import math
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("mailguard.health_score")

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "scoring_config.json")
_cached_config: Optional[dict] = None
_config_mtime: float = 0.0


def _load_config() -> dict:
    global _cached_config, _config_mtime
    try:
        mtime = os.path.getmtime(_CONFIG_PATH)
        if _cached_config is None or mtime != _config_mtime:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                _cached_config = json.load(f)
            _config_mtime = mtime
    except Exception:
        logger.warning("health_score_engine: nu am putut citi scoring_config.json, folosesc defaults")
        if _cached_config is None:
            _cached_config = _default_config()
    return _cached_config


def _default_config() -> dict:
    return {
        "decay_half_life_days": 45,
        "max_history_days": 365,
        "baseline_window_days": 90,
        "segment_thresholds": {"sanatos": 70.0, "neutru": 45.0, "la_risc": 25.0},
        "pillars": {
            "emotion": {"weight": 0.30},
            "effort": {"weight": 0.25},
            "operational": {"weight": 0.25},
            "relationship": {"weight": 0.20},
        },
        "emotion": {"sentiment_weight": 0.70, "emotional_intensity_penalty_factor": 0.15, "neutral_baseline": 0.65},
        "effort": {
            "repeat_issue_penalty": 0.25,
            "effort_signal_penalty_per_unit": 0.10,
            "max_effort_penalty": 0.40,
            "resolution_bonus": {
                "rezolvat": 0.10, "rezolvat_pe_loc": 0.15, "in_lucru": 0.0,
                "promisiune_follow_up": -0.05, "nerezolvat": -0.15, "n/a": 0.0, "informativ": 0.0,
            },
        },
        "operational": {
            "firefighting_window_days": 30,
            "max_firefighting_tasks": 5,
            "overdue_open_threshold_days": 7,
            "max_overdue_tasks": 3,
            "reopened_penalty_per_task": 0.10,
            "max_reopened_penalty": 0.30,
        },
        "relationship": {
            "warmth_weight": 0.50,
            "future_orientation_bonus": 0.10,
            "asks_questions_bonus": 0.05,
            "praise_flag_bonus_per_flag": 0.08,
            "silence_threshold_ratio": 0.40,
            "silence_window_days": 60,
            "silence_penalty": 0.25,
            "warmth_baseline_deviation_weight": 0.30,
        },
        "override_rules": [
            {
                "red_flags": ["mentiune_reziliere", "amenintare_legala", "ultimatum", "escaladare_management"],
                "window_days": 30,
                "force_segment": "critic",
            },
            {
                "red_flags": ["mentiune_concurenta", "mentiune_penalitati_contract", "cerere_export_date"],
                "window_days": 60,
                "min_segment": "la_risc",
            },
        ],
        "service_recovery": {
            "enabled": True,
            "window_days": 5,
            "negative_weight_reduction": 0.30,
            "requires_resolution_signal": ["rezolvat", "rezolvat_pe_loc"],
            "requires_positive_sentiment_threshold": 0.2,
        },
        "confidence": {
            "min_interactions_full": 10,
            "min_interactions_partial": 3,
            "low_confidence_label": "date_insuficiente",
        },
    }


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _decay(age_days: float, half_life: float) -> float:
    if half_life <= 0 or age_days < 0:
        return 1.0
    return math.exp(-math.log(2) * age_days / half_life)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _age_days(ts, now: datetime) -> float:
    if ts is None:
        return 0.0
    if hasattr(ts, "tzinfo") and ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return max(0.0, (now - ts).total_seconds() / 86400.0)


def _segment_from_score(score: float, cfg: dict, forced: Optional[str] = None) -> str:
    if forced:
        return forced
    thresholds = cfg.get("segment_thresholds", {"sanatos": 70.0, "neutru": 45.0, "la_risc": 25.0})
    if score >= thresholds["sanatos"]:
        return "sanatos"
    if score >= thresholds["neutru"]:
        return "neutru"
    if score >= thresholds["la_risc"]:
        return "la_risc"
    return "critic"


def _segment_rank(segment: str) -> int:
    return {"critic": 0, "la_risc": 1, "neutru": 2, "sanatos": 3}.get(segment, 2)


# ── Fetch interacțiuni din DB ─────────────────────────────────────────────────

def _fetch_interactions(client_id: int, cur, cfg: dict, now: datetime) -> List[dict]:
    """Returnează toate interacțiunile relevante din interaction_analysis pentru client."""
    max_days = int(cfg.get("max_history_days", 365))
    since = now - timedelta(days=max_days)

    cur.execute(
        """
        SELECT
            interaction_type, occurred_at, direction,
            sentiment_score, effort_signals, red_flags,
            analysis_json
        FROM interaction_analysis
        WHERE client_id = %s
          AND occurred_at >= %s
        ORDER BY occurred_at DESC
        """,
        (client_id, since),
    )
    rows = cur.fetchall()
    result = []
    for row in rows:
        if hasattr(row, "keys"):
            r = dict(row)
        else:
            keys = ["interaction_type", "occurred_at", "direction",
                    "sentiment_score", "effort_signals", "red_flags", "analysis_json"]
            r = dict(zip(keys, row))

        r["age_days"] = _age_days(r.get("occurred_at"), now)
        r["decay_w"] = _decay(r["age_days"], float(cfg.get("decay_half_life_days", 45)))

        aj = r.get("analysis_json") or {}
        if isinstance(aj, str):
            try:
                aj = json.loads(aj)
            except Exception:
                aj = {}
        r["_aj"] = aj
        result.append(r)
    return result


def _fetch_task_signals(iris_client_id, cur, cfg: dict, now: datetime) -> dict:
    """Semnale operaționale din task-uri CTS (firefighting, overdue, reopened)."""
    if not iris_client_id:
        return {"firefighting": 0, "overdue": 0, "reopened": 0}

    op_cfg = cfg.get("operational", {})
    ff_window = int(op_cfg.get("firefighting_window_days", 30))
    overdue_days = int(op_cfg.get("overdue_open_threshold_days", 7))
    ff_since = now - timedelta(days=ff_window)
    overdue_cutoff = now - timedelta(days=overdue_days)

    _RESOLVED = {"resolved", "closed", "done", "solved", "rezolvat", "inchis"}

    try:
        cur.execute(
            """
            SELECT COUNT(*) FROM cts_task_ground_truth
            WHERE client_id = %s AND cts_created_at >= %s
            """,
            (iris_client_id, ff_since),
        )
        row = cur.fetchone()
        firefighting = int(row[0] if not hasattr(row, "keys") else row["count"]) if row else 0
    except Exception:
        firefighting = 0

    try:
        cur.execute(
            """
            SELECT COUNT(*) FROM cts_task_ground_truth
            WHERE client_id = %s
              AND LOWER(status) != ALL(%s)
              AND cts_created_at <= %s
            """,
            (iris_client_id, list(_RESOLVED), overdue_cutoff),
        )
        row = cur.fetchone()
        overdue = int(row[0] if not hasattr(row, "keys") else row["count"]) if row else 0
    except Exception:
        overdue = 0

    reopened = 0

    return {"firefighting": firefighting, "overdue": overdue, "reopened": reopened}


# ── Service Recovery Detection ────────────────────────────────────────────────

def _detect_service_recovery(interactions: List[dict], cfg: dict) -> List[dict]:
    """Marchează interacțiunile negative urmate rapid de rezolvare pozitivă.

    O interacțiune negativă primește tag service_recovery=True dacă în
    <window_days> zile după ea există o interacțiune cu resolution_signal de tip
    'rezolvat'/'rezolvat_pe_loc' și sentiment pozitiv. Penalizarea ei e redusă.
    """
    sr_cfg = cfg.get("service_recovery", {})
    if not sr_cfg.get("enabled", True):
        return interactions

    window_days = float(sr_cfg.get("window_days", 5))
    ok_signals = set(sr_cfg.get("requires_resolution_signal", ["rezolvat", "rezolvat_pe_loc"]))
    pos_threshold = float(sr_cfg.get("requires_positive_sentiment_threshold", 0.2))

    sorted_by_time = sorted(interactions, key=lambda x: x.get("occurred_at") or datetime.min.replace(tzinfo=timezone.utc))
    for i, ia in enumerate(sorted_by_time):
        if (ia.get("sentiment_score") or 0) >= 0:
            continue
        ts_i = ia.get("occurred_at")
        if ts_i is None:
            continue
        if hasattr(ts_i, "tzinfo") and ts_i.tzinfo is None:
            ts_i = ts_i.replace(tzinfo=timezone.utc)

        for j in range(i + 1, len(sorted_by_time)):
            jb = sorted_by_time[j]
            ts_j = jb.get("occurred_at")
            if ts_j is None:
                continue
            if hasattr(ts_j, "tzinfo") and ts_j.tzinfo is None:
                ts_j = ts_j.replace(tzinfo=timezone.utc)
            delta_days = (ts_j - ts_i).total_seconds() / 86400.0
            if delta_days > window_days:
                break
            res_sig = jb.get("_aj", {}).get("resolution_signal", "")
            sent_j = jb.get("sentiment_score") or 0
            if res_sig in ok_signals and sent_j >= pos_threshold:
                ia["service_recovery"] = True
                break

    return sorted_by_time


# ── Pilon 1: Emotion ──────────────────────────────────────────────────────────

def _pillar_emotion(interactions: List[dict], cfg: dict) -> Tuple[float, int]:
    """Sentiment agregat cu decay + penalizare intensitate emoțională negativă."""
    em_cfg = cfg.get("emotion", {})
    sent_w = float(em_cfg.get("sentiment_weight", 0.70))
    intensity_pen = float(em_cfg.get("emotional_intensity_penalty_factor", 0.15))
    neutral_baseline = float(em_cfg.get("neutral_baseline", 0.65))
    sr_cfg = cfg.get("service_recovery", {})
    sr_reduction = float(sr_cfg.get("negative_weight_reduction", 0.30))

    w_sum = 0.0
    w_total = 0.0
    count = 0

    for ia in interactions:
        sent = ia.get("sentiment_score")
        if sent is None:
            continue
        sent = float(sent)
        dw = ia.get("decay_w", 1.0)

        # Service recovery: reducem ponderea negativului la sr_reduction
        if ia.get("service_recovery") and sent < 0:
            dw = dw * sr_reduction

        intensity = float(ia.get("_aj", {}).get("emotional_intensity", 0.5) or 0.5)

        # Normalizăm sentimentul de la [-1,1] la [0,1]
        sent_norm = (sent + 1.0) / 2.0

        # Penalizăm intensitate emoțională mare + sentiment negativ
        if sent < 0:
            intensity_adj = sent_norm - intensity * intensity_pen
        else:
            intensity_adj = sent_norm

        w_sum += intensity_adj * dw
        w_total += dw
        count += 1

    if w_total == 0 or count == 0:
        return neutral_baseline, 0

    raw = w_sum / w_total
    return _clamp(raw), count


# ── Pilon 2: Effort ───────────────────────────────────────────────────────────

def _pillar_effort(interactions: List[dict], cfg: dict) -> Tuple[float, int]:
    """Efortul clientului: repeat issues, effort signals, resolution signal."""
    ef_cfg = cfg.get("effort", {})
    repeat_pen = float(ef_cfg.get("repeat_issue_penalty", 0.25))
    effort_pen_unit = float(ef_cfg.get("effort_signal_penalty_per_unit", 0.10))
    max_effort_pen = float(ef_cfg.get("max_effort_penalty", 0.40))
    res_bonuses = ef_cfg.get("resolution_bonus", {})
    sr_cfg = cfg.get("service_recovery", {})
    sr_reduction = float(sr_cfg.get("negative_weight_reduction", 0.30))

    score = 1.0
    w_total = 0.0
    count = 0

    for ia in interactions:
        dw = ia.get("decay_w", 1.0)
        aj = ia.get("_aj", {})
        is_sr = ia.get("service_recovery", False)

        is_repeat = bool(aj.get("is_repeat_issue", False))
        effort_signals = int(aj.get("effort_signals", 0) or 0)
        res_signal = aj.get("resolution_signal", "n/a") or "n/a"

        penalty = 0.0
        if is_repeat:
            pen = repeat_pen
            if is_sr:
                pen *= sr_reduction
            penalty += pen
        if effort_signals > 0:
            pen = min(effort_signals * effort_pen_unit, max_effort_pen)
            if is_sr:
                pen *= sr_reduction
            penalty += pen

        bonus = float(res_bonuses.get(res_signal, 0.0))

        adjustment = bonus - penalty
        score += adjustment * dw
        w_total += dw
        count += 1

    if count == 0:
        return 0.65, 0

    # Normalizăm — scorul brut poate depăși [0,1] dacă toate bonusuri/penalizări acumulează
    # Folosim media ponderată: pornim de la 1.0 și aplicăm ajustări
    raw = score / max(w_total, 1.0) if w_total > 0 else 0.65
    return _clamp(raw / max(1.0, raw) if raw > 1.0 else raw), count


# ── Pilon 3: Operational ──────────────────────────────────────────────────────

def _pillar_operational(interactions: List[dict], task_signals: dict, cfg: dict) -> Tuple[float, int]:
    """Calitatea operațională: rezolvări, promisiuni nerespectate, taskuri firefighting."""
    op_cfg = cfg.get("operational", {})
    max_ff = float(op_cfg.get("max_firefighting_tasks", 5))
    max_overdue = float(op_cfg.get("max_overdue_tasks", 3))
    reopen_pen = float(op_cfg.get("reopened_penalty_per_task", 0.10))
    max_reopen = float(op_cfg.get("max_reopened_penalty", 0.30))

    ff = task_signals.get("firefighting", 0)
    overdue = task_signals.get("overdue", 0)
    reopened = task_signals.get("reopened", 0)

    ff_score = _clamp(1.0 - ff / max(max_ff, 1))
    overdue_score = _clamp(1.0 - overdue / max(max_overdue, 1))
    reopen_score = _clamp(1.0 - min(reopened * reopen_pen, max_reopen))

    # Semnale din interaction_analysis: resolution quality
    res_weights = {"rezolvat": 1.0, "rezolvat_pe_loc": 1.0, "in_lucru": 0.65,
                   "promisiune_follow_up": 0.50, "nerezolvat": 0.0, "n/a": 0.7, "informativ": 0.8}

    r_sum = 0.0
    r_total = 0.0
    ia_count = 0
    for ia in interactions:
        aj = ia.get("_aj", {})
        res = aj.get("resolution_signal", "n/a") or "n/a"
        val = res_weights.get(res, 0.7)
        dw = ia.get("decay_w", 1.0)
        r_sum += val * dw
        r_total += dw
        ia_count += 1

    resolution_score = (r_sum / r_total) if r_total > 0 else 0.7

    # Ponderare: resolution 50%, ff 25%, overdue 15%, reopen 10%
    combined = resolution_score * 0.50 + ff_score * 0.25 + overdue_score * 0.15 + reopen_score * 0.10
    return _clamp(combined), ia_count


# ── Pilon 4: Relationship ────────────────────────────────────────────────────

def _pillar_relationship(interactions: List[dict], cfg: dict, now: datetime) -> Tuple[float, int]:
    """Sănătatea relațională: warmth, future_orientation, dezangajare (tăcere)."""
    rel_cfg = cfg.get("relationship", {})
    warmth_w = float(rel_cfg.get("warmth_weight", 0.50))
    future_bonus = float(rel_cfg.get("future_orientation_bonus", 0.10))
    questions_bonus = float(rel_cfg.get("asks_questions_bonus", 0.05))
    praise_bonus_per = float(rel_cfg.get("praise_flag_bonus_per_flag", 0.08))
    silence_ratio = float(rel_cfg.get("silence_threshold_ratio", 0.40))
    silence_window = int(rel_cfg.get("silence_window_days", 60))
    silence_pen = float(rel_cfg.get("silence_penalty", 0.25))
    baseline_dev_w = float(rel_cfg.get("warmth_baseline_deviation_weight", 0.30))

    all_warmth = []
    recent_warmth = []
    futures = 0
    questions = 0
    praises = 0
    count = 0

    baseline_window = int(cfg.get("baseline_window_days", 90))
    baseline_cutoff = now - timedelta(days=baseline_window)

    for ia in interactions:
        aj = ia.get("_aj", {})
        warmth = aj.get("message_warmth")
        if warmth is None:
            continue
        warmth = float(warmth)
        dw = ia.get("decay_w", 1.0)
        all_warmth.append((warmth, dw))

        ts = ia.get("occurred_at")
        if ts and hasattr(ts, "tzinfo"):
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts >= baseline_cutoff:
                recent_warmth.append((warmth, dw))

        if aj.get("future_orientation"):
            futures += 1
        if aj.get("asks_questions"):
            questions += 1
        praises += len(aj.get("praise_flags") or [])
        count += 1

    if count == 0:
        return 0.60, 0

    # Warmth absolut (ponderat cu decay)
    warmth_num = sum(w * d for w, d in all_warmth)
    warmth_den = sum(d for _, d in all_warmth)
    avg_warmth = warmth_num / warmth_den if warmth_den > 0 else 0.5

    # Detectare deviație față de propria baseline (primele 90 zile vs recente)
    baseline_interactions = [ia for ia in interactions
                              if _age_days(ia.get("occurred_at"), now) > baseline_window]
    baseline_warmth_vals = []
    for ia in baseline_interactions:
        ww = ia.get("_aj", {}).get("message_warmth")
        if ww is not None:
            baseline_warmth_vals.append(float(ww))

    baseline_warmth = sum(baseline_warmth_vals) / len(baseline_warmth_vals) if baseline_warmth_vals else avg_warmth
    warmth_deviation = avg_warmth - baseline_warmth  # pozitiv = mai cald decât baseline = bine

    # Combinăm warmth absolut + deviație față de baseline
    warmth_score = _clamp(avg_warmth + warmth_deviation * baseline_dev_w)

    # Bonus pentru semnale pozitive relaționale
    bonus = 0.0
    if count > 0:
        future_rate = futures / count
        question_rate = questions / count
        bonus += future_rate * future_bonus
        bonus += question_rate * questions_bonus
    bonus += min(praises * praise_bonus_per, 0.20)

    # Penalizare tăcere (silence detection)
    silence_pen_applied = 0.0
    recent_cutoff = now - timedelta(days=silence_window)
    recent_count = sum(1 for ia in interactions
                       if (ia.get("occurred_at") or now) >= recent_cutoff)

    if baseline_warmth_vals:
        older_count = len(baseline_warmth_vals)
        expected_recent = older_count * (silence_window / baseline_window)
        if expected_recent > 2 and recent_count < expected_recent * silence_ratio:
            silence_pen_applied = silence_pen

    score = warmth_score * warmth_w + (1.0 - warmth_w) * (0.5 + bonus) - silence_pen_applied
    return _clamp(score), count


# ── Override Rules ────────────────────────────────────────────────────────────

def _check_overrides(interactions: List[dict], cfg: dict, now: datetime) -> Tuple[Optional[str], Optional[str], List[dict]]:
    """Verifică override-uri pe baza red_flags active.

    Returnează (force_segment, override_reason, active_red_flags_list).
    force_segment = None dacă nu există override activ.
    """
    override_rules = cfg.get("override_rules", [])
    active_flags_by_day = {}

    for ia in interactions:
        flags = ia.get("red_flags") or []
        ts = ia.get("occurred_at")
        if ts and hasattr(ts, "tzinfo") and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age = _age_days(ts, now)
        for f in (flags or []):
            if f not in active_flags_by_day or active_flags_by_day[f] > age:
                active_flags_by_day[f] = age

    force_segment = None
    override_reason = None
    active_flags_list = [
        {"flag": f, "age_days": round(d, 1)}
        for f, d in active_flags_by_day.items()
    ]

    for rule in override_rules:
        window = int(rule.get("window_days", 30))
        rule_flags = set(rule.get("red_flags", []))
        matching = [f for f, d in active_flags_by_day.items() if f in rule_flags and d <= window]
        if not matching:
            continue

        if "force_segment" in rule:
            # Force overrule: segment forțat indiferent de scor
            current_rank = _segment_rank(force_segment or "sanatos")
            forced_rank = _segment_rank(rule["force_segment"])
            if forced_rank < current_rank:
                force_segment = rule["force_segment"]
                override_reason = f"Red flags active ({', '.join(matching)}) în {window} zile → segment forțat {rule['force_segment']}"
        elif "min_segment" in rule:
            # Min segment: nu poate fi mai bun de min_segment
            min_seg = rule["min_segment"]
            if force_segment is None:
                force_segment = f"_min_{min_seg}"
                override_reason = f"Red flags ({', '.join(matching)}) → minim {min_seg}"

    return force_segment, override_reason, active_flags_list


def _apply_segment_override(
    computed_segment: str, force_segment: Optional[str], override_reason: Optional[str]
) -> Tuple[str, Optional[str]]:
    """Aplică override de segment respectând ierarhia (critic < la_risc < neutru < sanatos)."""
    if not force_segment:
        return computed_segment, None

    if force_segment.startswith("_min_"):
        min_seg = force_segment[5:]
        if _segment_rank(computed_segment) > _segment_rank(min_seg):
            return computed_segment, None
        return min_seg, override_reason

    # force exact
    if _segment_rank(force_segment) < _segment_rank(computed_segment):
        return force_segment, override_reason
    return computed_segment, None


# ── Confidence ────────────────────────────────────────────────────────────────

def _compute_confidence(n_interactions: int, cfg: dict) -> float:
    conf_cfg = cfg.get("confidence", {})
    full = int(conf_cfg.get("min_interactions_full", 10))
    partial = int(conf_cfg.get("min_interactions_partial", 3))

    if n_interactions >= full:
        return 1.0
    if n_interactions < partial:
        return 0.2 + 0.3 * (n_interactions / max(partial, 1))
    return 0.5 + 0.5 * ((n_interactions - partial) / max(full - partial, 1))


# ── Persistare ────────────────────────────────────────────────────────────────

def _save_health_score(client_id: int, result: dict, cur, conn) -> bool:
    score = result.get("score")
    pillar_scores = json.dumps(result.get("pillar_scores", {}))
    trend = result.get("trend")
    segment = result.get("segment")
    confidence = result.get("confidence")
    red_flags_active = json.dumps(result.get("red_flags_active", []))
    override_reason = result.get("override_reason")

    try:
        cur.execute(
            """
            INSERT INTO client_health_score
                (client_id, score, pillar_scores, trend, segment, confidence,
                 red_flags_active, override_reason, computed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (client_id) DO UPDATE SET
                score = EXCLUDED.score,
                pillar_scores = EXCLUDED.pillar_scores,
                trend = EXCLUDED.trend,
                segment = EXCLUDED.segment,
                confidence = EXCLUDED.confidence,
                red_flags_active = EXCLUDED.red_flags_active,
                override_reason = EXCLUDED.override_reason,
                computed_at = NOW()
            """,
            (client_id, score, pillar_scores, trend, segment, confidence,
             red_flags_active, override_reason),
        )

        # Snapshot zilnic (idempotent — ON CONFLICT DO NOTHING)
        today = datetime.now(timezone.utc).date()
        cur.execute(
            """
            INSERT INTO client_health_history
                (client_id, score, pillar_scores, segment, confidence, snapshotted_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (client_id, snapshotted_at) DO NOTHING
            """,
            (client_id, score, pillar_scores, segment, confidence, today),
        )

        conn.commit()
        return True
    except Exception:
        conn.rollback()
        logger.error("health_score_engine: DB save failed for client_id=%s", client_id, exc_info=True)
        return False


# ── Trend Calculation ─────────────────────────────────────────────────────────

def _compute_trend(client_id: int, cur, current_score: Optional[float]) -> Optional[float]:
    """Panta scorului pe ultimele 90 zile din client_health_history (regresia liniară simplă)."""
    if current_score is None:
        return None
    try:
        cur.execute(
            """
            SELECT score, snapshotted_at
            FROM client_health_history
            WHERE client_id = %s
              AND snapshotted_at >= CURRENT_DATE - INTERVAL '90 days'
            ORDER BY snapshotted_at ASC
            """,
            (client_id,),
        )
        rows = cur.fetchall()
        if len(rows) < 2:
            return None

        points = []
        for row in rows:
            if hasattr(row, "keys"):
                s, d = row["score"], row["snapshotted_at"]
            else:
                s, d = row[0], row[1]
            if s is None:
                continue
            if hasattr(d, "toordinal"):
                x = d.toordinal()
            else:
                x = 0
            points.append((x, float(s)))

        if len(points) < 2:
            return None

        n = len(points)
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        x_mean = sum(xs) / n
        y_mean = sum(ys) / n
        num = sum((xs[i] - x_mean) * (ys[i] - y_mean) for i in range(n))
        den = sum((xs[i] - x_mean) ** 2 for i in range(n))
        if den == 0:
            return 0.0
        slope = num / den  # puncte per zi
        return round(slope * 30, 3)  # pantă pe 30 zile
    except Exception:
        return None


# ── API Public ────────────────────────────────────────────────────────────────

def compute_health_score(
    client_id: int,
    cur,
    conn,
    iris_client_id: Optional[int] = None,
    now: Optional[datetime] = None,
    save: bool = True,
) -> dict:
    """Calculează scorul de sănătate v2 pentru un client.

    Params:
        client_id: ID client din tabelul `clients`
        cur: cursor psycopg2 (RealDictCursor sau standard)
        conn: conexiune psycopg2 (pentru commit)
        iris_client_id: ID client în CTS (pentru task-uri), opțional
        now: moment de referință (default: now UTC)
        save: dacă True, salvează în client_health_score + client_health_history

    Returns:
        dict cu: score, segment, pillar_scores, confidence, red_flags_active,
                 override_reason, trend, n_interactions, computed_at, low_confidence
    """
    if now is None:
        now = _now_utc()

    cfg = _load_config()

    interactions = _fetch_interactions(client_id, cur, cfg, now)
    interactions = _detect_service_recovery(interactions, cfg)

    task_signals = _fetch_task_signals(iris_client_id, cur, cfg, now)

    n = len(interactions)
    confidence = _compute_confidence(n, cfg)

    if n == 0:
        result = {
            "score": None,
            "segment": None,
            "pillar_scores": {},
            "confidence": round(confidence, 3),
            "red_flags_active": [],
            "override_reason": None,
            "trend": None,
            "n_interactions": 0,
            "computed_at": now.isoformat(),
            "low_confidence": True,
            "error": "no_data",
        }
        if save:
            _save_health_score(client_id, result, cur, conn)
        return result

    # Calculăm cei 4 piloni
    emotion_score, emotion_n = _pillar_emotion(interactions, cfg)
    effort_score, effort_n = _pillar_effort(interactions, cfg)
    operational_score, operational_n = _pillar_operational(interactions, task_signals, cfg)
    relationship_score, relationship_n = _pillar_relationship(interactions, cfg, now)

    pillar_scores = {
        "emotion": round(emotion_score * 100, 1),
        "effort": round(effort_score * 100, 1),
        "operational": round(operational_score * 100, 1),
        "relationship": round(relationship_score * 100, 1),
    }

    # Ponderi din config
    pillar_weights = {k: v.get("weight", 0.25) for k, v in cfg.get("pillars", {}).items()}
    w_emotion = pillar_weights.get("emotion", 0.30)
    w_effort = pillar_weights.get("effort", 0.25)
    w_operational = pillar_weights.get("operational", 0.25)
    w_relationship = pillar_weights.get("relationship", 0.20)

    total_w = w_emotion + w_effort + w_operational + w_relationship
    if total_w <= 0:
        total_w = 1.0

    combined = (
        emotion_score * w_emotion +
        effort_score * w_effort +
        operational_score * w_operational +
        relationship_score * w_relationship
    ) / total_w

    score = round(_clamp(combined) * 100, 1)

    # Override-uri
    force_segment, override_reason, active_flags = _check_overrides(interactions, cfg, now)
    computed_segment = _segment_from_score(score, cfg)
    final_segment, final_override = _apply_segment_override(computed_segment, force_segment, override_reason)

    # Trend din istoric
    trend = _compute_trend(client_id, cur, score)

    conf_cfg = cfg.get("confidence", {})
    low_conf = confidence < 0.5
    low_conf_label = conf_cfg.get("low_confidence_label", "date_insuficiente") if low_conf else None

    result = {
        "score": score,
        "segment": final_segment,
        "pillar_scores": pillar_scores,
        "confidence": round(confidence, 3),
        "red_flags_active": active_flags,
        "override_reason": final_override,
        "trend": trend,
        "n_interactions": n,
        "computed_at": now.isoformat(),
        "low_confidence": low_conf,
        **({"low_confidence_label": low_conf_label} if low_conf_label else {}),
    }

    if save:
        _save_health_score(client_id, result, cur, conn)

    return result


def batch_compute(
    client_ids: List[int],
    cur,
    conn,
    iris_client_map: Optional[Dict[int, int]] = None,
    now: Optional[datetime] = None,
    save: bool = True,
) -> dict:
    """Calculează scorul pentru o listă de clienți.

    Params:
        client_ids: lista de ID-uri client
        iris_client_map: {client_id: iris_client_id} pentru task-uri (opțional)
        save: dacă True, persistă rezultatele

    Returns:
        {"computed": N, "errors": M, "results": {client_id: result}}
    """
    if now is None:
        now = _now_utc()
    if iris_client_map is None:
        iris_client_map = {}

    stats = {"computed": 0, "errors": 0, "results": {}}

    for cid in client_ids:
        try:
            iris_id = iris_client_map.get(cid)
            result = compute_health_score(cid, cur, conn, iris_client_id=iris_id, now=now, save=save)
            stats["results"][cid] = result
            stats["computed"] += 1
        except Exception:
            logger.error("batch_compute: eroare pentru client_id=%s", cid, exc_info=True)
            stats["errors"] += 1

    return stats
