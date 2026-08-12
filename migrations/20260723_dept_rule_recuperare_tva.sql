-- Reguli deterministe „Recuperare TVA extern" în settings->'rules' (department_rules).
-- Idempotent: adaugă fiecare regulă DOAR dacă id-ul ei nu există deja în array.
-- Necesar pe orice mediu (staging + prod) fiindcă release-ul NU migrează conținutul tabelei settings.
-- Match: subiect „rambursare tva extern" SAU corp cu frazele-semnal ale dosarului de recuperare TVA.

DO $$
DECLARE
    v_rules jsonb;
    v_new jsonb;
    r jsonb;
BEGIN
    -- dacă rândul nu există deloc, nu forțăm nimic (seed-ul din cod îl va crea la prima citire)
    SELECT value->'rules' INTO v_rules FROM settings WHERE key = 'department_rules';
    IF v_rules IS NULL THEN
        RAISE NOTICE 'department_rules absent — seed-ul din cod se va ocupa la prima citire; skip.';
        RETURN;
    END IF;

    FOR r IN SELECT * FROM jsonb_array_elements(
        jsonb_build_array(
            jsonb_build_object(
                'id','rtva_subj01','department','recuperare_tva',
                'from','','subject','rambursare tva extern','body','',
                'enabled', true,
                'note','Subiect rambursare TVA extern -> recuperare_tva',
                'by','migration_20260723','at','2026-07-23T00:00:00+00:00'),
            jsonb_build_object(
                'id','rtva_body01','department','recuperare_tva',
                'from','','subject','','body','dosarul de recuperare tva',
                'enabled', true,
                'note','Corp: dosarul de recuperare TVA -> recuperare_tva',
                'by','migration_20260723','at','2026-07-23T00:00:00+00:00'),
            jsonb_build_object(
                'id','rtva_body02','department','recuperare_tva',
                'from','','subject','','body','situatia dosarului dumneavoastra pentru recuperare tva',
                'enabled', true,
                'note','Corp: situatia dosarului pentru recuperare TVA -> recuperare_tva',
                'by','migration_20260723','at','2026-07-23T00:00:00+00:00')
        )
    )
    LOOP
        -- adaugă doar dacă id-ul nu există deja
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
           updated_by = 'migration_20260723_dept_rule_recuperare_tva',
           updated_at = NOW()
     WHERE key = 'department_rules';
END $$;
