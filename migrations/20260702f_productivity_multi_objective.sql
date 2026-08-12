-- 2026-07-02: Productivitate -- obiective multiple per departament (email/task/apel),
-- start cu Suport 1 (Mailuri 45%, Task-uri 25%, Task-uri CargoBox 5%, Apeluri 25%).
-- Aditiv + idempotent, fara operatii distructive (fara DROP/DELETE) -- constraint-ul se
-- adauga doar daca lipseste, iar randurile Suport 1 se upsert-eaza (nu se mai sterg cele
-- din afara setului tinta, ca sa nu existe risc la rularea pe alta baza la Release).
-- Coloana `unitate` distinge apelurile (secunde) de restul (minute) -- comparatia in cod
-- ramane pe valoarea bruta, unitatea e doar pt afisare/documentare.

ALTER TABLE productivity_objective ADD COLUMN IF NOT EXISTS unitate text NOT NULL DEFAULT 'minute';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'productivity_objective_unitate_check'
    ) THEN
        ALTER TABLE productivity_objective ADD CONSTRAINT productivity_objective_unitate_check
            CHECK (unitate IN ('minute', 'secunde'));
    END IF;
END $$;

-- Suport 1: upsert direct pe cele 4 obiective (email/120/45, task/120/25, task-cargobox/8400/5,
-- apel/4/25) -- randul unic vechi (email/120/100) e acoperit de ON CONFLICT pe (department, tip,
-- COALESCE(categorie, '')), fara sa mai fie nevoie sa stergem nimic.
INSERT INTO productivity_objective (department, tip, categorie, limita_minute, pondere, unitate)
VALUES
  ('suport_1', 'email', NULL,       120,  45, 'minute'),
  ('suport_1', 'task',  NULL,       120,  25, 'minute'),
  ('suport_1', 'task',  'cargobox', 8400,  5, 'minute'),
  ('suport_1', 'apel',  NULL,         4,  25, 'secunde')
ON CONFLICT (department, tip, COALESCE(categorie, ''))
DO UPDATE SET limita_minute = EXCLUDED.limita_minute, pondere = EXCLUDED.pondere, unitate = EXCLUDED.unitate;
