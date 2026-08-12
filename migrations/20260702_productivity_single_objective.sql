-- 2026-07-02: Productivitate — un singur obiectiv (fara categorie) per departament.
-- Follow-up la 20260701_productivity_module.sql / 20260701_productivity_suport3.sql.
-- Colapseaza obiectivele per-categorie (informatie/sesizare/reclamatie) intr-un singur
-- obiectiv general per (departament, tip). Limita pastrata = a obiectivului cu pondere
-- maxima (tie -> id minim). Pondere -> 100 (irelevanta cu un singur obiectiv).
-- Aditiv + idempotent: sare peste departamentele deja normalizate (un rand, categorie NULL).

DO $mig$
DECLARE
  r RECORD;
  keep_limit integer;
BEGIN
  FOR r IN SELECT DISTINCT department, tip FROM productivity_objective LOOP
    -- deja normalizat? (exact un rand, categorie NULL) -> skip
    IF (SELECT count(*) FROM productivity_objective
          WHERE department = r.department AND tip = r.tip) = 1
       AND (SELECT bool_or(categorie IS NULL) FROM productivity_objective
              WHERE department = r.department AND tip = r.tip) THEN
      CONTINUE;
    END IF;

    SELECT limita_minute INTO keep_limit
      FROM productivity_objective
      WHERE department = r.department AND tip = r.tip
      ORDER BY pondere DESC, id ASC
      LIMIT 1;

    DELETE FROM productivity_objective WHERE department = r.department AND tip = r.tip;

    INSERT INTO productivity_objective(department, tip, categorie, limita_minute, pondere)
      VALUES (r.department, r.tip, NULL, keep_limit, 100);
  END LOOP;
END
$mig$;
