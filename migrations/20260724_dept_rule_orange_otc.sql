-- Regulă deterministă: cod autentificare Orange (OTC) -> Suport 2.
-- Expeditor noreply.otc@orange.com => department suport_2 (erau pe Suport 1).
-- Idempotent: adaugă regula DOAR dacă id-ul ei nu există deja în settings->'rules'.
-- Necesar pe orice mediu (staging + prod) fiindcă release-ul NU migrează conținutul tabelei settings.

DO $$
DECLARE
    v_rules jsonb;
    r jsonb;
BEGIN
    SELECT value->'rules' INTO v_rules FROM settings WHERE key = 'department_rules';
    IF v_rules IS NULL THEN
        RAISE NOTICE 'department_rules absent — seed-ul din cod se va ocupa la prima citire; skip.';
        RETURN;
    END IF;

    FOR r IN SELECT * FROM jsonb_array_elements(
        jsonb_build_array(
            jsonb_build_object(
                'id','orange-otc-01','department','suport_2',
                'from','noreply.otc@orange.com','subject','','body','',
                'enabled', true,
                'note','Cod autentificare Orange (OTC) -> Suport 2',
                'by','migration_20260724','at','2026-07-24T00:00:00+00:00')
        )
    )
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM jsonb_array_elements(v_rules) AS e
            WHERE e->>'id' = r->>'id'
        ) THEN
            v_rules := v_rules || jsonb_build_array(r);
            RAISE NOTICE 'Adaugat regula %', r->>'id';
        ELSE
            RAISE NOTICE 'Regula % exista deja — skip', r->>'id';
        END IF;
    END LOOP;

    UPDATE settings
       SET value = jsonb_set(value, '{rules}', v_rules),
           updated_by = 'migration_20260724_dept_rule_orange_otc',
           updated_at = NOW()
     WHERE key = 'department_rules';
END $$;
