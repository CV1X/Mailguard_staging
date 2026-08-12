-- Fix regula determinista 54d9492e: from='cosmin' (prea lax) -> 'cosmin.bogdan@cargotrack.ro'
-- Regula prindea orice expeditor cu "cosmin" in adresa/nume (ex. cosmin.radu2001@yahoo.com)
-- si il incadra fals pe mobilitate. Intentionat doar angajatul intern cosmin.bogdan@cargotrack.ro.
-- Migratie 20260720 sarise update-ul (merge pe id nu suprascrie existente).

UPDATE settings
SET value = jsonb_set(
    value,
    '{rules}',
    (
        SELECT jsonb_agg(
            CASE
                WHEN rule->>'id' = '54d9492e'
                THEN rule
                    || '{"from": "cosmin.bogdan@cargotrack.ro"}'::jsonb
                    || '{"note": "Cosmin Bogdan intern (@cargotrack.ro) -> mobilitate"}'::jsonb
                    || jsonb_build_object('at', to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US+00:00'), 'by', 'migration:fix-cosmin-rule-54d9492e')
                ELSE rule
            END
        )
        FROM jsonb_array_elements(value->'rules') AS rule
    )
),
updated_by = 'migration:fix-cosmin-rule-54d9492e',
updated_at = NOW()
WHERE key = 'department_rules';
