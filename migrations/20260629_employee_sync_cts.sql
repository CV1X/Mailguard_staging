-- 2026-06-29: OPS-2026-0132 — activare sync angajati din IRIS (endpoint LIVE /cts/employees).
-- Aditiv + idempotent. Completeaza migratia 20260629_employee_iris_sync.sql cu:
--   * coloane pentru datele reale din /cts/employees (work_hours, break_minutes, days pe program)
--   * config corect: endpoint_path real, mapare departament IRIS->Cargo360, sync ACTIV.
-- IRIS livreaza department_slug cu cratime (recuperare-tva, suport-1, taxe-de-drum); Cargo360
-- foloseste underscore (recuperare_tva, suport_1, taxe_drum). Angajatii din departamente care NU
-- exista in Cargo360 (HR, Marketing, Management...) sunt IGNORATI de serviciu (nu se importa).
-- 'shift' ramane MANUAL (IRIS trimite null) — sync-ul NU il suprascrie niciodata.

-- 1) Coloane noi pe maparea de angajati (ore lucru/pauza, informativ pt disponibilitate)
ALTER TABLE employee_department_mapping ADD COLUMN IF NOT EXISTS work_hours    integer;
ALTER TABLE employee_department_mapping ADD COLUMN IF NOT EXISTS break_minutes integer;

-- 2) Numar de zile pe intrarea de program (planned_leave aduce 'days'; invoirile orare nu)
ALTER TABLE employee_schedule ADD COLUMN IF NOT EXISTS days integer;

-- 3) Config sync: path real + mapare departament + ACTIVARE.
--    (UPDATE, nu INSERT ON CONFLICT — randurile exista deja din migratia anterioara.)
UPDATE settings SET value='"/cts/employees"'::jsonb, updated_at=now()
  WHERE key='employee_sync.endpoint_path';

UPDATE settings SET value='{
    "recuperare-tva":"recuperare_tva",
    "suport-1":"suport_1","suport-2":"suport_2","suport-3":"suport_3",
    "taxe-de-drum":"taxe_drum","taxe-drum":"taxe_drum",
    "conta":"contabilitate","contabilitate":"contabilitate",
    "mobilitate":"mobilitate","comercial":"comercial"
  }'::jsonb, updated_at=now()
  WHERE key='employee_sync.department_map';

UPDATE settings SET value='true'::jsonb, updated_at=now()
  WHERE key='employee_sync.enabled';

-- Daca rulam pe un mediu unde migratia anterioara n-a apucat sa seedeze cheile (defensiv):
INSERT INTO settings(key, value, description) VALUES
  ('employee_sync.enabled',       'true'::jsonb,            'OPS-0132: sync zilnic angajati din IRIS (LIVE /cts/employees)'),
  ('employee_sync.endpoint_path', '"/cts/employees"'::jsonb,'OPS-0132: path relativ la iris_api_url pt lista angajati'),
  ('employee_sync.department_map', '{"recuperare-tva":"recuperare_tva","suport-1":"suport_1","suport-2":"suport_2","suport-3":"suport_3","taxe-de-drum":"taxe_drum","taxe-drum":"taxe_drum","conta":"contabilitate","contabilitate":"contabilitate","mobilitate":"mobilitate","comercial":"comercial"}'::jsonb, 'OPS-0132: mapare departament IRIS -> slug Cargo360'),
  ('employee_sync.last_sync_at',  'null'::jsonb,            'OPS-0132: timestamp ultima sincronizare reusita'),
  ('employee_sync.last_result',   'null'::jsonb,            'OPS-0132: rezumat ultima sincronizare')
ON CONFLICT (key) DO NOTHING;
