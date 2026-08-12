"""Backfill DEPARTAMENT pe emailurile existente — DOAR reguli deterministe + default suport_1.

Fara apeluri AI (ieftin). Pentru emailurile clean fara departament: aplica
department_rules.match; ce nu se potriveste -> suport_1. Reviziile manuale corecteaza ulterior
restul fuzzy.

Rulare:
  cd /opt/iris-mailguard && sudo venv/bin/python -m scripts.backfill_departments
Optiuni:
  --all   include si emailurile care nu sunt 'clean' (implicit: doar status='clean')
"""
import sys
import json
from collections import Counter

from sqlalchemy import text
from app.database import SessionLocal
from app.services import department_rules

FALLBACK = "suport_1"


def _run(db, rows, allow_default):
    """allow_default=True (clean): non-match -> suport_1. False (non-clean): non-match -> skip."""
    tally = Counter()
    by_rule, by_default, skipped = 0, 0, 0
    for r in rows:
        em = dict(r._mapping)
        hit = department_rules.match(em, db=db)
        if hit:
            dep, rule = hit
            res = {"department": dep, "confidence": 1.0, "model": "rule",
                   "rule_id": rule.get("id"), "reason": "Backfill regula: " + (rule.get("note") or "")}
            by_rule += 1
        elif allow_default:
            dep = FALLBACK
            res = {"department": FALLBACK, "confidence": None, "model": "fallback",
                   "reason": "Backfill: niciun match de regula -> departament general."}
            by_default += 1
        else:
            skipped += 1
            continue  # non-clean fara regula -> lasam NULL (nu fortam suport_1 pe spam/auto_report)
        db.execute(text(
            "UPDATE emails SET ai_department=:d, ai_department_result=CAST(:r AS jsonb), "
            "ai_department_at=NOW() WHERE id=:id"),
            {"d": dep, "r": json.dumps(res), "id": em["id"]})
        tally[dep] += 1
    db.commit()
    return by_rule, by_default, skipped, tally


def main():
    db = SessionLocal()
    cols = "id, subject, from_address, from_name, body_text, body_html"
    # Pasul 1 — clean fara departament: reguli + default suport_1.
    clean = db.execute(text(
        "SELECT " + cols + " FROM emails WHERE ai_department IS NULL AND status='clean' ORDER BY id")).fetchall()
    r1, d1, s1, t1 = _run(db, clean, allow_default=True)
    print("Clean: %d | prin regula %d | default suport_1 %d" % (len(clean), r1, d1))
    # Pasul 2 — non-clean (auto_report/spam/carantina), EXCLUS NDR: DOAR reguli (update-if-match).
    nonclean = db.execute(text(
        "SELECT " + cols + " FROM emails WHERE ai_department IS NULL "
        "AND status NOT IN ('clean','ndr') ORDER BY id")).fetchall()
    r2, d2, s2, t2 = _run(db, nonclean, allow_default=False)
    print("Non-clean: %d | prin regula %d | lasate NULL %d" % (len(nonclean), r2, s2))
    total = t1 + t2
    print("Distributie (total atins):")
    for dep, n in total.most_common():
        print("  %-16s %d" % (dep, n))
    db.close()


if __name__ == "__main__":
    main()
