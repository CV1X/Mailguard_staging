-- Data de la care angajatul intră în calculul de productivitate (perioadă probă / onboarding).
-- NULL = angajat activ de la începuturi (inclus în toate lunile).
-- Dacă productivity_start_date > ultima zi a lunii calculate → exclus din calcul.
ALTER TABLE employee_department_mapping
    ADD COLUMN IF NOT EXISTS productivity_start_date DATE;

COMMENT ON COLUMN employee_department_mapping.productivity_start_date
    IS 'Data de la care se ține cont de prezență în calcule productivitate (NULL = mereu inclus).';
