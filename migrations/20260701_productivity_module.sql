-- 2026-07-01: Modul Productivitate (mailuri) — faza 1 (Suport 1/2, Taxe de drum).
-- Aditiv + idempotent. Config obiective+ponderi per departament; scorarea pe timp ramane
-- inerta (achieved% = "date insuficiente") pana CTS trimite un timp de solutionare real.

-- 1) Config per departament (baza pentru obiectivul real)
CREATE TABLE IF NOT EXISTS productivity_department_config (
    department   text PRIMARY KEY,
    baza_procent numeric(5,2) NOT NULL DEFAULT 95,
    updated_at   timestamptz DEFAULT now(),
    updated_by   text
);

-- 2) Obiective (0..N per departament); tip='email' acum, viitor task/apel
CREATE TABLE IF NOT EXISTS productivity_objective (
    id            bigserial PRIMARY KEY,
    department    text NOT NULL,
    tip           text NOT NULL DEFAULT 'email',
    categorie     text,                    -- NULL = general (toate categoriile)
    limita_minute integer NOT NULL,
    pondere       numeric(5,2) NOT NULL,
    created_at    timestamptz DEFAULT now()
);
-- un singur obiectiv per (departament, tip, categorie) — categorie NULL tratata ca ''
CREATE UNIQUE INDEX IF NOT EXISTS productivity_objective_uidx
    ON productivity_objective (department, tip, COALESCE(categorie,''));

-- 3) Seed config departamente (editabil in UI)
INSERT INTO productivity_department_config (department, baza_procent) VALUES
    ('suport_1', 95), ('suport_2', 95), ('taxe_drum', 95)
ON CONFLICT (department) DO NOTHING;

-- 4) Seed obiective starter (doar daca departamentul nu are inca obiective email)
INSERT INTO productivity_objective (department, tip, categorie, limita_minute, pondere)
SELECT d.department, 'email', v.categorie, v.limita, v.pondere
FROM (VALUES ('suport_1'), ('suport_2'), ('taxe_drum')) AS d(department)
CROSS JOIN (VALUES
    ('informatie', 120, 50.0),
    ('sesizare',   100, 25.0),
    ('reclamatie',  60, 25.0)
) AS v(categorie, limita, pondere)
WHERE NOT EXISTS (
    SELECT 1 FROM productivity_objective o
    WHERE o.department = d.department AND o.tip = 'email'
);

-- 5) Sarbatori legale RO (zile nelucratoare) pt zile_lucratoare = L-V minus aceste date
INSERT INTO settings(key, value, description) VALUES (
  'productivity.ro_holidays',
  '["2026-01-01","2026-01-02","2026-01-06","2026-01-07","2026-01-24","2026-04-10","2026-04-12","2026-04-13","2026-05-01","2026-05-31","2026-06-01","2026-08-15","2026-11-30","2026-12-01","2026-12-25","2026-12-26","2027-01-01","2027-01-02","2027-01-06","2027-01-07","2027-01-24","2027-04-30","2027-05-01","2027-05-02","2027-05-03","2027-06-01","2027-06-20","2027-06-21","2027-08-15","2027-11-30","2027-12-01","2027-12-25","2027-12-26"]'::jsonb,
  'Productivitate: sarbatori legale RO (zile nelucratoare) pt zile_lucratoare = L-V minus aceste date'
) ON CONFLICT (key) DO NOTHING;
