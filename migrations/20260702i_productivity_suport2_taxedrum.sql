-- 2026-07-02: Productivitate -- obiective multiple pt Suport 2 (email/task/device_ops) si
-- Taxe de drum (email/apel/task + familii BGToll/E-Toll/HU-GO/CargoBox), mirror pe
-- 20260702f_productivity_multi_objective.sql (Suport 1). Aditiv + idempotent, fara DROP/DELETE.
-- baza_procent (95.00) e deja setat pt ambele departamente in productivity_department_config,
-- nu se modifica aici.
--
-- Nota Suport 2: ponderile insumeaza 92% (nu 100%), confirmat explicit cu userul -- codul
-- normalizeaza media ponderata dupa suma ponderilor active (nu presupune total=100), deci
-- functioneaza corect si asa.

INSERT INTO productivity_objective (department, tip, categorie, limita_minute, pondere, unitate)
VALUES
  ('suport_2', 'email',      NULL,             120, 20, 'minute'),
  ('suport_2', 'task',       NULL,             240, 20, 'minute'),
  ('suport_2', 'device_ops', 'instalare_noua', 300, 10, 'minute'),
  ('suport_2', 'device_ops', 'calibrare',      360, 10, 'minute'),
  ('suport_2', 'device_ops', 'interventie',    360, 10, 'minute'),
  ('suport_2', 'device_ops', 'inlocuire',      300,  7, 'minute'),
  ('suport_2', 'device_ops', 'demontare',      480,  5, 'minute'),
  ('suport_2', 'device_ops', 'mutare',         360,  5, 'minute'),
  ('suport_2', 'device_ops', 'periferice',     360,  5, 'minute'),

  ('taxe_drum', 'email', NULL,        120, 30, 'minute'),
  ('taxe_drum', 'apel',  NULL,          4, 10, 'secunde'),
  ('taxe_drum', 'task',  NULL,        120, 20, 'minute'),
  ('taxe_drum', 'task',  'bgtoll',   2880, 10, 'minute'),
  ('taxe_drum', 'task',  'etoll',    1440, 10, 'minute'),
  ('taxe_drum', 'task',  'hugo',     1440, 10, 'minute'),
  ('taxe_drum', 'task',  'cargobox', 1440, 10, 'minute')
ON CONFLICT (department, tip, COALESCE(categorie, ''))
DO UPDATE SET limita_minute = EXCLUDED.limita_minute, pondere = EXCLUDED.pondere, unitate = EXCLUDED.unitate;
