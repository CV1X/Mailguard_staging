-- Pontaj CTS per angajat (nu doar boolean pe departament ca department_attendance).
-- Alimentat de app/services/pontaj_sync.py::sync_attendance() din payload-ul /cts/timesheets
-- (fiecare rand de departament contine si employees[] cu nume/interval/minute).
CREATE TABLE IF NOT EXISTS employee_attendance (
  id              BIGSERIAL PRIMARY KEY,
  cts_employee_id TEXT NOT NULL,
  employee_id     INTEGER REFERENCES employee_department_mapping(id) ON DELETE SET NULL,
  full_name       TEXT NOT NULL,
  department      TEXT NOT NULL,
  work_date       DATE NOT NULL,
  present         BOOLEAN NOT NULL DEFAULT true,
  begin_time      TIMESTAMP,
  end_time        TIMESTAMP,
  minutes         INTEGER,
  source          TEXT NOT NULL DEFAULT 'cts_pontaj',
  synced_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (cts_employee_id, work_date)
);

CREATE INDEX IF NOT EXISTS employee_attendance_dept_date_idx
  ON employee_attendance(department, work_date);
