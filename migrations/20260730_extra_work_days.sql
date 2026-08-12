-- 2026-07-30: zile libere extra pentru lucru pe proiecte / refurbished.
-- Zile de lucru care NU sunt suport efectiv — se scad din ore_disponibile exact
-- ca un concediu, dar se exprima ca NUMAR de zile pe (an, luna), fara date concrete.
-- Aditiv + idempotent. Reutilizeaza employee_schedule (kind='project_work'/'refurbished',
-- entry_source='manual_extra', start_date/end_date NULL).
--
-- Regula de timing (identica cu concediile): intra in calcul doar daca sunt adaugate
-- INAINTE de inceputul lunii vizate. Odata snapshot-ul lunii creat (prima zi lucratoare,
-- la trimiterea raportului lunar), targetele NU se mai ajusteaza.
-- Imutabile dupa creare: se pot doar sterge (nu exista UPDATE).

ALTER TABLE employee_schedule ADD COLUMN IF NOT EXISTS days_count   integer;
ALTER TABLE employee_schedule ADD COLUMN IF NOT EXISTS period_year  integer;
ALTER TABLE employee_schedule ADD COLUMN IF NOT EXISTS period_month integer;
ALTER TABLE employee_schedule ADD COLUMN IF NOT EXISTS created_at   timestamptz NOT NULL DEFAULT now();

-- Lookup rapid la calculul lunar (forecast + raport)
CREATE INDEX IF NOT EXISTS employee_schedule_extra_period_idx
    ON employee_schedule (period_year, period_month, employee_id)
    WHERE kind IN ('project_work', 'refurbished');

-- O singura intrare per (angajat, tip, luna).
-- NOTA: employee_schedule_uidx existent are cheia (employee_id, kind, COALESCE(leave_type,''),
-- COALESCE(start_date,'0001-01-01'), COALESCE(end_date,'0001-01-01')). Cu start/end NULL, doua
-- luni diferite ar colida pe acelasi (angajat, tip). De aceea intrarile extra scriu si
-- leave_type='YYYY-MM' — discriminant in cheia existenta. Indexul de mai jos e explicit
-- pentru acelasi invariant, ca sa nu depinda de trucul cu leave_type.
CREATE UNIQUE INDEX IF NOT EXISTS employee_schedule_extra_uidx
    ON employee_schedule (employee_id, kind, period_year, period_month)
    WHERE kind IN ('project_work', 'refurbished');

-- Integritate: intrarile extra au zile+perioada, fara interval de date
-- Adaugam constrangerea idempotent (fara DROP — compatibil cu release pipeline).
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'employee_schedule_extra_chk'
          AND conrelid = 'employee_schedule'::regclass
    ) THEN
        ALTER TABLE employee_schedule ADD CONSTRAINT employee_schedule_extra_chk CHECK (
            kind NOT IN ('project_work', 'refurbished')
            OR (days_count IS NOT NULL AND days_count > 0
                AND period_year IS NOT NULL AND period_month BETWEEN 1 AND 12
                AND start_date IS NULL AND end_date IS NULL)
        );
    END IF;
END $$;
