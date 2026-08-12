-- Fix: departamentul task-urilor CTS nu era aliasat la slug-ul canonic.
--
-- Constatare (staging, 2026-07-29): `cts_task_ground_truth.department` conținea `taxe_de_drum`
-- pe 21.959 rânduri, dar `employee_department_mapping.department` (canonicul folosit peste tot
-- în UI și în configurarea obiectivelor) e `taxe_drum`. `_slug()` din cts_tasks_sync normaliza
-- doar spații/cratime, fără aliasare.
--
-- Efect măsurat, aceeași lună și același departament:
--   ecranele care filtrează pe `cts_task_ground_truth.department = 'taxe_drum'`
--     (productivity.py:1366 istoric, :1495 per-operator)     -> 0 task-uri
--   ecranele care fac JOIN pe angajat (`edm.department`)
--     (productivity.py:469 forecast, :1771 analytics)        -> 21.870 task-uri
-- Adică productivitatea departamentului Taxe de drum apărea fie 0, fie completă, în funcție
-- de ecran. Aceeași clasă de problemă pe `operational` (4 rânduri) -> `management_operational`.
--
-- Idempotent: re-rularea nu mai găsește valorile vechi.

UPDATE cts_task_ground_truth SET department = 'taxe_drum', updated_at = NOW()
WHERE department = 'taxe_de_drum';

UPDATE cts_task_ground_truth SET department = 'management_operational', updated_at = NOW()
WHERE department = 'operational';

-- Verificare (informativă în log-ul migrației): task-uri al căror departament nu corespunde
-- departamentului angajatului asignat. Ar trebui 0 după alias.
DO $$
DECLARE n INT;
BEGIN
    SELECT count(*) INTO n
    FROM cts_task_ground_truth t
    JOIN employee_department_mapping e ON e.id = t.assignee_employee_id
    WHERE t.department IS DISTINCT FROM e.department;
    RAISE NOTICE 'task-uri cu department != departamentul angajatului: %', n;
END $$;
