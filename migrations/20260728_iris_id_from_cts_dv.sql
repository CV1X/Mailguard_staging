-- Populează iris_id în employee_department_mapping din cts_dv_employee (match pe first_name + last_name).
-- Mapare unică (skip dacă match multiplu). iris_id = CTS employee id, folosit de sync vacation.
-- Idempotent: UPDATE doar dacă iris_id IS NULL sau diferit.

UPDATE employee_department_mapping edm
SET iris_id = sub.cts_id::text
FROM (
    SELECT edm2.id AS edm_id, MIN(dv.id) AS cts_id, COUNT(dv.id) AS matches
    FROM employee_department_mapping edm2
    JOIN cts_dv_employee dv ON (
        lower(trim(dv.first_name)) || ' ' || lower(trim(dv.last_name)) = lower(trim(edm2.name))
        OR lower(trim(dv.last_name)) || ' ' || lower(trim(dv.first_name)) = lower(trim(edm2.name))
        OR lower(replace(trim(dv.first_name), '-', ' ')) || ' ' || lower(trim(dv.last_name)) = lower(trim(edm2.name))
    )
    WHERE edm2.enabled = true
    GROUP BY edm2.id
    HAVING COUNT(dv.id) = 1
) sub
WHERE edm.id = sub.edm_id
  AND (edm.iris_id IS NULL OR edm.iris_id <> sub.cts_id::text);

-- Șterge din employee_schedule înregistrările vacation_approved pre-2026 (date istorice irelevante).
-- Sursa de adevăr rămâne cts_dv_employee_vacation_request; sync-ul repopulează 2026+.
DELETE FROM employee_schedule
WHERE kind = 'vacation_approved'
  AND entry_source = 'cts'
  AND start_date < '2026-01-01';

-- Populează vacation_approved 2026+ din DV prin iris_id (idempotent).
INSERT INTO employee_schedule (employee_id, kind, leave_type, start_date, end_date, status, days, raw, entry_source)
SELECT
    edm.id,
    'vacation_approved',
    'concediu',
    v.period_begin::date,
    v.period_end::date,
    'approved',
    v.days::int,
    '{}',
    'cts'
FROM cts_dv_employee_vacation_request v
JOIN employee_department_mapping edm ON edm.iris_id::text = v.employee_id::text
WHERE v.status::int = 2
  AND (v.deleted_at IS NULL OR v.deleted_at::text = '')
  AND v.period_begin::date >= '2026-01-01'
ON CONFLICT DO NOTHING;
