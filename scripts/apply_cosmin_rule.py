"""One-time: insera regula body-only Cosmin (daca lipseste din store-ul deja seedat) si
re-aplica regulile deterministe pe emailurile NON-manuale care contin adresa lui Cosmin in fir.

Sigur: respecta precedenta din department_rules.match (o regula from/subject reala bate body-only),
NU atinge ai_department_manual=true (corectiile operatorului raman intacte), idempotent.

Rulare: cd /opt/iris-mailguard && sudo /opt/iris-mailguard/venv/bin/python -m scripts.apply_cosmin_rule
"""
import json
from sqlalchemy import text
from app.database import SessionLocal
from app.services import department_rules as DR

COSMIN = "cosmin.bogdan@cargotrack.ro"


def main():
    db = SessionLocal()

    # 1) Insereaza regula body-only Cosmin daca nu exista deja (store-ul e deja seedat).
    rules = DR.list_all(db)
    has = any((r.get("body") or "").strip().lower() == COSMIN for r in rules)
    if has:
        print("Regula Cosmin (body) exista deja — skip insert.")
    else:
        res = DR.add_rule(db, {
            "department": "mobilitate", "from": "", "subject": "", "body": COSMIN,
            "note": "Cosmin Bogdan in fir -> Mobilitate",
        }, by="cristian-raul.covaci")
        print("Regula Cosmin adaugata:", res.get("ok"), res.get("rule", {}).get("id"))

    # 2) Re-aplica regulile pe candidatii NON-manuali care contin adresa Cosmin in corp.
    rows = db.execute(text(
        "SELECT id, subject, from_address, from_name, body_text, body_html, ai_department "
        "FROM emails WHERE (ai_department_manual IS NOT TRUE) "
        "AND (body_text ILIKE :p OR body_html ILIKE :p) ORDER BY id"),
        {"p": "%" + COSMIN + "%"}).fetchall()
    print("Candidati non-manuali cu Cosmin in fir: %d" % len(rows))

    changed = 0
    for r in rows:
        em = dict(r._mapping)
        hit = DR.match(em, db=db)
        if not hit:
            continue
        dep, rule = hit
        if dep == em.get("ai_department"):
            continue  # deja corect
        dres = {"department": dep, "confidence": 1.0, "model": "rule", "rule_id": rule.get("id"),
                "reason": "Re-aplicare regula: " + (rule.get("note") or "")}
        db.execute(text(
            "UPDATE emails SET ai_department=:d, ai_department_result=CAST(:r AS jsonb), "
            "ai_department_at=NOW() WHERE id=:id"),
            {"d": dep, "r": json.dumps(dres), "id": em["id"]})
        changed += 1
        print("  #%s  %s -> %s  (%s)" % (em["id"], em.get("ai_department"), dep, rule.get("note")))
    db.commit()
    print("Actualizate: %d" % changed)
    db.close()


if __name__ == "__main__":
    main()
