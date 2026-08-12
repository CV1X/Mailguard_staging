-- 2026-07-02: Suport 2 -- adauga obiectivul 'apel' (4 sec, 8%) lipsa din migratia anterioara
-- (20260702i_productivity_suport2_taxedrum.sql) -- confirmat de user din tab-ul Obiective &
-- Ponderi. Cu acest rand, ponderile Suport 2 insumeaza corect 100%
-- (20+20+8+10+10+10+7+5+5+5=100), nu 92% cum au fost aplicate initial. Aditiv + idempotent.

INSERT INTO productivity_objective (department, tip, categorie, limita_minute, pondere, unitate)
VALUES
  ('suport_2', 'apel', NULL, 4, 8, 'secunde')
ON CONFLICT (department, tip, COALESCE(categorie, ''))
DO UPDATE SET limita_minute = EXCLUDED.limita_minute, pondere = EXCLUDED.pondere, unitate = EXCLUDED.unitate;
