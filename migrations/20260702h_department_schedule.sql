-- 2026-07-02: program de lucru per departament + calcul SLA in program de lucru (nu 24/7).
-- Aditiv + idempotent. Vezi CLAUDE.md (app) sectiunea "REGULA OBLIGATORIE migratii -> productie".
--
-- department_schedule: program saptamanal per departament (weekday ISO: 1=Luni..7=Duminica).
--   requires_attendance=true => ziua e considerata neacoperita pana nu exista rand cu present=true
--   in department_attendance (folosit azi doar pt Sambata, care depinde de pontaj CTS neintegrat inca).
-- department_attendance: tabel INERT, pregatit pt sincronizare pontaj din CTS (mirror pattern
--   employee_sync din 20260629_employee_iris_sync.sql -- gol/oprit pana la grant, vezi outbox).
-- business_minutes(): functie folosita de app/services/productivity.py in locul EXTRACT(EPOCH...)
--   brut, ca sa nu conteze orele in afara programului de lucru al departamentului catre SLA.

CREATE TABLE IF NOT EXISTS department_schedule (
    department          text        NOT NULL,
    weekday             smallint    NOT NULL CHECK (weekday BETWEEN 1 AND 7),
    start_time          time        NOT NULL,
    end_time            time        NOT NULL,
    active              boolean     NOT NULL DEFAULT true,
    requires_attendance boolean     NOT NULL DEFAULT false,
    updated_by          varchar(100),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (department, weekday)
);

CREATE TABLE IF NOT EXISTS department_attendance (
    department text        NOT NULL,
    work_date  date        NOT NULL,
    present    boolean     NOT NULL DEFAULT false,
    source     text        NOT NULL DEFAULT 'cts_pontaj',
    synced_at  timestamptz,
    PRIMARY KEY (department, work_date)
);

INSERT INTO settings(key, value, description) VALUES
  ('pontaj_sync.enabled',       'false'::jsonb, 'OPS-department_schedule: sync pontaj din CTS (inert pana la grant IRIS Gateway)'),
  ('pontaj_sync.endpoint_path', '"/cts/timesheets"'::jsonb, 'OPS-department_schedule: path placeholder relativ la iris_api_url pt pontaj (nu e inca LIVE)'),
  ('pontaj_sync.last_sync_at',  'null'::jsonb, 'OPS-department_schedule: timestamp ultima sincronizare pontaj reusita'),
  ('pontaj_sync.last_result',   'null'::jsonb, 'OPS-department_schedule: rezumat ultima sincronizare pontaj')
ON CONFLICT (key) DO NOTHING;

-- business_minutes: minute din [p_start, p_end] care cad in programul de lucru al departamentului,
-- excluzand sarbatorile (p_holidays) si zilele fara acoperire (schedule lipsa/inactiv, sau
-- requires_attendance=true fara rand present=true in department_attendance). STABLE (nu IMMUTABLE):
-- citeste department_schedule/department_attendance, al caror continut se poate schimba.
CREATE OR REPLACE FUNCTION business_minutes(
    p_dept     text,
    p_start    timestamptz,
    p_end      timestamptz,
    p_holidays date[] DEFAULT ARRAY[]::date[]
) RETURNS numeric AS $$
DECLARE
    v_start_local timestamp;
    v_end_local   timestamp;
    v_day         date;
    v_last_day    date;
    v_sched       RECORD;
    v_day_start   timestamp;
    v_day_end     timestamp;
    v_ov_start    timestamp;
    v_ov_end      timestamp;
    v_total       numeric := 0;
    v_holidays    date[];
    v_iter        integer := 0;
BEGIN
    IF p_start IS NULL OR p_end IS NULL OR p_end <= p_start THEN
        RETURN NULL;
    END IF;
    v_holidays := COALESCE(p_holidays, ARRAY[]::date[]);
    v_start_local := p_start AT TIME ZONE 'Europe/Bucharest';
    v_end_local   := p_end   AT TIME ZONE 'Europe/Bucharest';
    v_day      := v_start_local::date;
    v_last_day := v_end_local::date;

    WHILE v_day <= v_last_day AND v_iter < 731 LOOP
        v_iter := v_iter + 1;

        IF v_day = ANY(v_holidays) THEN
            v_day := v_day + 1;
            CONTINUE;
        END IF;

        SELECT start_time, end_time, requires_attendance INTO v_sched
          FROM department_schedule
          WHERE department = p_dept
            AND weekday = EXTRACT(ISODOW FROM v_day)::smallint
            AND active = true;

        IF NOT FOUND THEN
            v_day := v_day + 1;
            CONTINUE;
        END IF;

        IF v_sched.requires_attendance THEN
            PERFORM 1 FROM department_attendance
              WHERE department = p_dept AND work_date = v_day AND present = true;
            IF NOT FOUND THEN
                v_day := v_day + 1;
                CONTINUE;
            END IF;
        END IF;

        v_day_start := v_day::timestamp + v_sched.start_time;
        v_day_end   := v_day::timestamp + v_sched.end_time;
        v_ov_start  := GREATEST(v_day_start, v_start_local);
        v_ov_end    := LEAST(v_day_end, v_end_local);
        IF v_ov_end > v_ov_start THEN
            v_total := v_total + EXTRACT(EPOCH FROM (v_ov_end - v_ov_start)) / 60.0;
        END IF;

        v_day := v_day + 1;
    END LOOP;

    RETURN v_total;
END;
$$ LANGUAGE plpgsql STABLE;
