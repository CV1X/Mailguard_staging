"""Regenereaza prompturile de DEPARTAMENT din divergentele CTS reziduale (semnal curat dupa
reclasificarea fresh). Reutilizeaza logica endpoint-ului /ai/department/regenerate-prompts?use_cts=true:
construieste fp/fn (puse gresit aici / ar fi trebuit aici), cheama modelul (no_cache) sa RESCRIE
promptul departamentului, recupereaza JSON-ul, face BACKUP si UPSERT in ai_department_prompts.

Rulare: sudo /opt/iris-mailguard/venv/bin/python /opt/iris-mailguard/scripts/regen_dept_prompts.py
"""
import os, sys
for line in open("/opt/iris-mailguard/.env", encoding="utf-8"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip())
sys.path.insert(0, "/opt/iris-mailguard")
import psycopg2, psycopg2.extras
from app.config import get_settings
from app.services import department_classifier as D
from app.services import iris_ai
from app.api.v1.ai_department import _regen_system_one, _salvage_prompt_json

TARGETS = ["contabilitate", "suport_2", "taxe_drum", "comercial", "mobilitate", "recuperare_tva", "suport_1"]
MODEL = "claude-haiku-4-5-20251001"

DIV_SQL = """
SELECT e.ai_department AS old_department, gt.cts_department AS new_department,
       e.subject, LEFT(COALESCE(e.body_text, e.body_html, ''), 300) AS snippet
FROM cts_ground_truth gt JOIN emails e ON e.id=gt.email_id
WHERE COALESCE(gt.cts_direction,'received')='received'
  AND gt.cts_department IS NOT NULL AND e.ai_department IS NOT NULL
  AND gt.cts_department <> e.ai_department
  AND (e.ai_department=%(d)s OR gt.cts_department=%(d)s)
ORDER BY gt.changed_at DESC NULLS LAST, gt.id DESC LIMIT 200
"""


def build_content(dep, prompts, corr):
    fp = [m for m in corr if m["old_department"] == dep]
    fn = [m for m in corr if m["new_department"] == dep]
    lines = ["DEPARTAMENT TINTA: " + D.DEPT_LABELS[dep] + " (" + dep + ")",
             "\nPROMPT ACTUAL:\n" + (prompts.get(dep) or "")]
    if fp:
        lines.append("\n\n[A] Emailuri pe care AI le-a pus GRESIT in acest departament (de fapt "
                     "apartin altui departament) - promptul e PREA LARG, clarifica ce NU apartine:")
        for i, m in enumerate(fp, 1):
            lines.append("\n(%d) Corect era: %s | Subiect: %s\n    Continut: %s" % (
                i, m["new_department"], m["subject"] or "(gol)", (m["snippet"] or "").strip()))
    if fn:
        lines.append("\n\n[B] Emailuri care AR FI TREBUIT puse in acest departament dar AI le-a pus "
                     "altundeva - promptul e PREA INGUST, adauga indiciile lipsa:")
        for i, m in enumerate(fn, 1):
            lines.append("\n(%d) AI a pus gresit in: %s | Subiect: %s\n    Continut: %s" % (
                i, m["old_department"], m["subject"] or "(gol)", (m["snippet"] or "").strip()))
    return "\n".join(lines), len(fp), len(fn)


def main():
    s = get_settings()
    conn = psycopg2.connect(host=s.db_host, port=s.db_port, dbname=s.db_name,
                            user=s.db_user, password=s.db_password)
    conn.autocommit = True
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # BACKUP idempotent
    cur.execute("DROP TABLE IF EXISTS ai_department_prompts_bak_20260626")
    cur.execute("CREATE TABLE ai_department_prompts_bak_20260626 AS SELECT * FROM ai_department_prompts")
    print("backup -> ai_department_prompts_bak_20260626", flush=True)

    prompts = D.load_prompts()
    for dep in TARGETS:
        cur.execute(DIV_SQL, {"d": dep})
        corr = [dict(r) for r in cur.fetchall()]
        if not corr:
            print("[%s] fara divergente - skip" % dep, flush=True)
            continue
        content, n_fp, n_fn = build_content(dep, prompts, corr)
        res = iris_ai.run_prompt(_regen_system_one(dep), content, response_format="json",
                                 model_hint=MODEL, temperature=0.2, max_tokens=4500,
                                 task="cargo360:dept_prompt_regen", no_cache=True)
        parsed = res.get("parsed") or {}
        v = parsed.get("prompt") if isinstance(parsed, dict) else None
        if not (isinstance(v, str) and v.strip()):
            err = res.get("error") if isinstance(res.get("error"), dict) else {}
            raw = res.get("text") or err.get("raw_text") or ""
            salv = _salvage_prompt_json(raw)
            if salv:
                parsed = salv; v = parsed.get("prompt")
        if not (isinstance(v, str) and v.strip()):
            print("[%s] REGEN ESUAT (fp=%d fn=%d): %s" % (dep, n_fp, n_fn, res.get("error")), flush=True)
            continue
        new_prompt = v.strip()
        old_len = len(prompts.get(dep) or "")
        cur.execute(
            "INSERT INTO ai_department_prompts(department, prompt_text, updated_at, updated_by) "
            "VALUES (%s, %s, NOW(), 'cc-agent:regen-cts') "
            "ON CONFLICT (department) DO UPDATE SET prompt_text=EXCLUDED.prompt_text, "
            "updated_at=NOW(), updated_by=EXCLUDED.updated_by",
            (dep, new_prompt))
        print("[%s] SALVAT fp=%d fn=%d | len %d -> %d | %s" % (
            dep, n_fp, n_fn, old_len, len(new_prompt),
            (parsed.get("explicatie") or "")[:160]), flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
