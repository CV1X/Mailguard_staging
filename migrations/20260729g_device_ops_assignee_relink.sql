-- Completare la 20260729f: normalizare assignee + relink, re-rulabilă.
--
-- 20260729f a curățat rândurile existente la momentul rulării, dar sync-urile care au rulat
-- înainte de deployul codului nou au reintrodus valorile murdare. În plus, `VALID_DEPARTMENTS`
-- din iris_employee_sync avea doar 8 departamente din 16, deci angajații de la `instalari`
-- (Adrian Jurca, Cristian Gotonoaga) erau RESPINȘI la import — fără ei, relink-ul nu avea
-- pe cine să lege. După extinderea whitelist-ului, 6 angajați noi s-au importat.
--
-- Typo suplimentar găsit: CTS scrie `cristian.gotonoaca@` (c), rosterul IRIS are
-- `cristian.gotonoaga@` (g) — 65 operațiuni pierdute pe o literă.
--
-- Rulează în ordinea: normalizare -> relink. Idempotentă.

-- ── 1. Normalizare (repetă f, pentru rândurile intrate între timp) ──────────
UPDATE device_operations
SET assignee_raw = replace(lower(assignee_raw), '@cagrotrack.ro', '@cargotrack.ro'), updated_at = NOW()
WHERE lower(assignee_raw) LIKE '%@cagrotrack.ro';

UPDATE device_operations
SET assignee_raw = lower(assignee_raw) || '@cargotrack.ro', updated_at = NOW()
WHERE assignee_raw IS NOT NULL AND assignee_raw <> '' AND assignee_raw NOT LIKE '%@%'
  AND lower(assignee_raw) ~ '^[a-z0-9._%+-]+$'
  AND lower(assignee_raw) NOT IN ('client', 'nealocat');

-- ── 2. Typo în partea locală: gotonoaca -> gotonoaga ───────────────────────
UPDATE device_operations
SET assignee_raw = 'cristian.gotonoaga@cargotrack.ro', updated_at = NOW()
WHERE lower(assignee_raw) = 'cristian.gotonoaca@cargotrack.ro';

-- ── 3. Relink la angajații existenți local ─────────────────────────────────
UPDATE device_operations d
SET assignee_employee_id = e.id, updated_at = NOW()
FROM employee_department_mapping e
WHERE d.assignee_employee_id IS NULL AND lower(d.assignee_raw) = lower(e.email);

-- ── 4. Completează departamentul din angajat ───────────────────────────────
UPDATE device_operations d
SET department = e.department, updated_at = NOW()
FROM employee_department_mapping e
WHERE d.assignee_employee_id = e.id
  AND (d.department IS NULL OR d.department = '' OR d.department <> e.department);

DO $$
DECLARE tot INT; mapat INT; ph INT;
BEGIN
    SELECT count(*), count(assignee_employee_id) INTO tot, mapat FROM device_operations;
    SELECT count(*) INTO ph FROM device_operations
     WHERE assignee_employee_id IS NULL
       AND (assignee_raw IS NULL OR assignee_raw = ''
            OR lower(assignee_raw) IN ('client@cargotrack.ro','nealocat@cargotrack.ro'));
    RAISE NOTICE 'device_operations: % total, % cu angajat, % placeholder/gol (nemapabil prin definitie)',
                 tot, mapat, ph;
END $$;
