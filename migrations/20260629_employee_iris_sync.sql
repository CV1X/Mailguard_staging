-- 2026-06-29: OPS-2026-0132 — pregatire sincronizare zilnica angajati din IRIS.
-- Aditiv + idempotent. Endpointul IRIS e cerut prin outbox #11 (in asteptare grant);
-- pana atunci coloanele/tabela exista dar raman goale (sync INERT). Randurile manuale
-- existente primesc sync_source='manual' si NU sunt atinse de reconcile-ul de sync.

-- 1) Coloane noi pe maparea de angajati
ALTER TABLE employee_department_mapping ADD COLUMN IF NOT EXISTS email          text;
ALTER TABLE employee_department_mapping ADD COLUMN IF NOT EXISTS status         text;
ALTER TABLE employee_department_mapping ADD COLUMN IF NOT EXISTS shift          text;
ALTER TABLE employee_department_mapping ADD COLUMN IF NOT EXISTS sync_source    text NOT NULL DEFAULT 'manual';
ALTER TABLE employee_department_mapping ADD COLUMN IF NOT EXISTS iris_id        text;
ALTER TABLE employee_department_mapping ADD COLUMN IF NOT EXISTS last_synced_at timestamptz;

-- email unic (case-insensitive), doar cand e prezent — cheie de upsert pt sync
CREATE UNIQUE INDEX IF NOT EXISTS employee_dept_mapping_email_uidx
    ON employee_department_mapping (lower(email)) WHERE email IS NOT NULL AND email <> '';
-- nume unic (case-insensitive) — fallback de upsert cand IRIS nu trimite email
CREATE UNIQUE INDEX IF NOT EXISTS employee_dept_mapping_name_uidx
    ON employee_department_mapping (lower(name));

-- 2) Program/concedii/leave — one-to-many (0..N intrari per angajat)
CREATE TABLE IF NOT EXISTS employee_schedule (
    id          bigserial PRIMARY KEY,
    employee_id integer NOT NULL REFERENCES employee_department_mapping(id) ON DELETE CASCADE,
    kind        text NOT NULL,
    leave_type  text,
    start_date  date,
    end_date    date,
    status      text,
    raw         jsonb,
    synced_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS employee_schedule_emp_idx  ON employee_schedule(employee_id);
CREATE INDEX IF NOT EXISTS employee_schedule_kind_idx ON employee_schedule(kind);
CREATE UNIQUE INDEX IF NOT EXISTS employee_schedule_uidx
    ON employee_schedule(employee_id, kind, COALESCE(leave_type,''), COALESCE(start_date,'0001-01-01'), COALESCE(end_date,'0001-01-01'));

-- 3) Config sync (inert pana la grant). department_map gol => fallback suport_1 in cod.
INSERT INTO settings(key, value, description) VALUES
  ('employee_sync.enabled',       'false'::jsonb,               'OPS-0132: sync zilnic angajati din IRIS (off pana la grant outbox #11)'),
  ('employee_sync.endpoint_path', '"/api/v1/employees"'::jsonb, 'OPS-0132: path relativ la iris_api_url pt lista angajati (de confirmat cu Razvan)'),
  ('employee_sync.department_map', '{}'::jsonb,                 'OPS-0132: mapare departament IRIS -> slug Cargo360'),
  ('employee_sync.last_sync_at',  'null'::jsonb,                'OPS-0132: timestamp ultima sincronizare reusita'),
  ('employee_sync.last_result',   'null'::jsonb,                'OPS-0132: rezumat ultima sincronizare')
ON CONFLICT (key) DO NOTHING;
