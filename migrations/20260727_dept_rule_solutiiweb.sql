-- Regula departament: info@solutiiweb.ro -> contabilitate
-- Toate emailurile de la acest expeditor merg automat pe Contabilitate.
-- Idempotent: nu adauga daca regula cu id 'solutiiweb-conta-01' exista deja.

UPDATE settings
SET value = jsonb_set(
    value,
    '{rules}',
    (value->'rules') || '[{
        "id":         "solutiiweb-conta-01",
        "department": "contabilitate",
        "from":       "info@solutiiweb.ro",
        "subject":    "",
        "body":       "",
        "enabled":    true,
        "note":       "info@solutiiweb.ro -> contabilitate (regula explicita)",
        "by":         "migration_20260727",
        "at":         "2026-07-27T00:00:00+00:00"
    }]'::jsonb
)
WHERE key = 'department_rules'
  AND NOT (value->'rules') @> '[{"id": "solutiiweb-conta-01"}]'::jsonb;
