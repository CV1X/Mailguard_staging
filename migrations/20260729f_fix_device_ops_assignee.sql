-- Fix: assignee-ul operațiunilor pe dispozitive nu se mapa la angajat din cauza datelor murdare.
--
-- Constatare (staging, 2026-07-29): din 1.429 operațiuni, doar 654 aveau `assignee_employee_id`.
-- Cele 775 rămase, pe cauze:
--   275  assignee_raw gol                      -> nerezolvabil
--   165  `client@cargotrack.ro`                -> placeholder, nu e persoană
--   132  `adrian.jurca@cagrotrack.ro`          -> TYPO de domeniu (cagrotrack), persoană reală
--    49  `cosmin.margauan`                     -> username fără domeniu, persoană reală
--    20  `nealocat@cargotrack.ro`              -> placeholder
--   134  adrese valide, dar angajatul lipsea din employee_department_mapping
-- Adică munca a doi oameni reali (181 operațiuni) nu se contoriza nicăieri, din cauza a două
-- litere inversate și a unui domeniu lipsă.
--
-- Codul: `device_ops_sync._normalize_assignee_email()` corectează typo-ul, completează domeniul
-- intern și respinge placeholder-ele, ÎNAINTE de rezolvarea angajatului (care are deja fallback
-- de import automat din IRIS).
--
-- Migrația: normalizează `assignee_raw` retroactiv și re-leagă angajații care există deja local.
-- Cei care încă nu există în employee_department_mapping se vor lega la următorul sync
-- (import automat din rosterul IRIS).
--
-- Idempotent: re-rularea nu mai găsește valorile murdare.

-- ── 1. Corectează typo-ul de domeniu ────────────────────────────────────────
UPDATE device_operations
SET assignee_raw = replace(lower(assignee_raw), '@cagrotrack.ro', '@cargotrack.ro'),
    updated_at = NOW()
WHERE lower(assignee_raw) LIKE '%@cagrotrack.ro';

-- ── 2. Completează domeniul intern pentru username-urile fără domeniu ───────
UPDATE device_operations
SET assignee_raw = lower(assignee_raw) || '@cargotrack.ro', updated_at = NOW()
WHERE assignee_raw IS NOT NULL
  AND assignee_raw <> ''
  AND assignee_raw NOT LIKE '%@%'
  AND lower(assignee_raw) ~ '^[a-z0-9._%+-]+$'
  AND lower(assignee_raw) NOT IN ('client', 'nealocat');

-- ── 3. Re-leagă angajaților existenți local ─────────────────────────────────
UPDATE device_operations d
SET assignee_employee_id = e.id, updated_at = NOW()
FROM employee_department_mapping e
WHERE d.assignee_employee_id IS NULL
  AND lower(d.assignee_raw) = lower(e.email);

-- ── 4. Aliniază departamentul la slug-ul canonic (aceeași problemă ca la task-uri) ──
UPDATE device_operations SET department = 'management_operational', updated_at = NOW()
WHERE department IN ('operational', 'Operational');

UPDATE device_operations SET department = 'taxe_drum', updated_at = NOW()
WHERE department = 'taxe_de_drum';

-- ── 5. Completează departamentul din angajatul asignat, unde lipsește ───────
UPDATE device_operations d
SET department = e.department, updated_at = NOW()
FROM employee_department_mapping e
WHERE d.assignee_employee_id = e.id
  AND (d.department IS NULL OR d.department = '');

DO $$
DECLARE tot INT; mapat INT;
BEGIN
    SELECT count(*), count(assignee_employee_id) INTO tot, mapat FROM device_operations;
    RAISE NOTICE 'device_operations: % total, % cu angajat mapat', tot, mapat;
END $$;
