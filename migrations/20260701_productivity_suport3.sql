-- Productivitate: adauga departamentul "Suport 3" (aceeasi logica ca suport_1/2, taxe_drum).
-- Aditiv + idempotent (WHERE NOT EXISTS). In UI apare alfabetic inainte de "taxe_drum"
-- (list_configs -> ORDER BY department: suport_3 < taxe_drum). Depinde de tabelele create in
-- 20260701_productivity_module.sql (aplicat inainte prin sort C pe nume).

INSERT INTO productivity_department_config (department, baza_procent, updated_by)
SELECT 'suport_3', 95, 'migration:20260701_productivity_suport3'
WHERE NOT EXISTS (SELECT 1 FROM productivity_department_config WHERE department='suport_3');

INSERT INTO productivity_objective (department, tip, categorie, limita_minute, pondere)
SELECT 'suport_3', 'email', 'informatie', 120, 50
WHERE NOT EXISTS (SELECT 1 FROM productivity_objective
                  WHERE department='suport_3' AND tip='email' AND COALESCE(categorie,'')='informatie');

INSERT INTO productivity_objective (department, tip, categorie, limita_minute, pondere)
SELECT 'suport_3', 'email', 'sesizare', 100, 25
WHERE NOT EXISTS (SELECT 1 FROM productivity_objective
                  WHERE department='suport_3' AND tip='email' AND COALESCE(categorie,'')='sesizare');

INSERT INTO productivity_objective (department, tip, categorie, limita_minute, pondere)
SELECT 'suport_3', 'email', 'reclamatie', 60, 25
WHERE NOT EXISTS (SELECT 1 FROM productivity_objective
                  WHERE department='suport_3' AND tip='email' AND COALESCE(categorie,'')='reclamatie');
