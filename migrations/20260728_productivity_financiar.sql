-- 2026-07-28: Productivitate — departamente Financiar (contabilitate + recuperare_tva)
-- Obiective identice cu Suport 1: email/120min/50%, apel/4sec/25%, task/120min/25%
-- Aditiv + idempotent (IF NOT EXISTS / ON CONFLICT DO NOTHING / DO UPDATE)

INSERT INTO productivity_department_config (department, baza_procent, updated_by)
VALUES
  ('contabilitate',  95, 'migration:20260728_productivity_financiar'),
  ('recuperare_tva', 95, 'migration:20260728_productivity_financiar')
ON CONFLICT (department) DO NOTHING;

INSERT INTO productivity_objective (department, tip, categorie, limita_minute, pondere, unitate)
VALUES
  ('contabilitate',  'email', NULL, 120,  50, 'minute'),
  ('contabilitate',  'apel',  NULL,   4,  25, 'secunde'),
  ('contabilitate',  'task',  NULL, 120,  25, 'minute'),
  ('recuperare_tva', 'email', NULL, 120,  50, 'minute'),
  ('recuperare_tva', 'apel',  NULL,   4,  25, 'secunde'),
  ('recuperare_tva', 'task',  NULL, 120,  25, 'minute')
ON CONFLICT (department, tip, COALESCE(categorie, ''))
DO UPDATE SET limita_minute = EXCLUDED.limita_minute,
              pondere       = EXCLUDED.pondere,
              unitate       = EXCLUDED.unitate;
