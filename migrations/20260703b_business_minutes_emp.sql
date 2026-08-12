-- 2026-07-03: business_minutes_emp() -- varianta care foloseste orele REALE ale operatorului
-- din employee_attendance (begin_time/end_time UTC naive) in loc de department_schedule fix.
-- SLA curge doar cat operatorul era efectiv prezent si in tura sa.
-- Fallback la department_schedule daca nu exista inregistrare de pontaj pentru ziua respectiva.
-- Folosit in _fetch_email_rows/_fetch_task_rows/_fetch_device_ops_rows/_analytics din productivity.py.
CREATE OR REPLACE FUNCTION business_minutes_emp(
    p_dept        text,
    p_employee_id int,
    p_start       timestamptz,
    p_end         timestamptz,
    p_holidays    date[] DEFAULT ARRAY[]::date[]
) RETURNS numeric AS $$
DECLARE
    v_start_local timestamp;
    v_end_local   timestamp;
    v_day         date;
    v_last_day    date;
    v_work_start  timestamp;
    v_work_end    timestamp;
    v_sched       RECORD;
    v_att         RECORD;
    v_ov_start    timestamp;
    v_ov_end      timestamp;
    v_total       numeric := 0;
    v_holidays    date[];
    v_iter        integer := 0;
BEGIN
    IF p_start IS NULL OR p_end IS NULL OR p_end <= p_start THEN
        RETURN NULL;
    END IF;
    v_holidays    := COALESCE(p_holidays, ARRAY[]::date[]);
    v_start_local := p_start AT TIME ZONE 'Europe/Bucharest';
    v_end_local   := p_end   AT TIME ZONE 'Europe/Bucharest';
    v_day         := v_start_local::date;
    v_last_day    := v_end_local::date;

    WHILE v_day <= v_last_day AND v_iter < 731 LOOP
        v_iter := v_iter + 1;

        -- Sarbatoare legala → skip
        IF v_day = ANY(v_holidays) THEN
            v_day := v_day + 1;
            CONTINUE;
        END IF;

        -- Cauta prezenta individuala a operatorului
        SELECT present, begin_time, end_time
          INTO v_att
          FROM employee_attendance
         WHERE employee_id = p_employee_id AND work_date = v_day;

        IF FOUND THEN
            IF NOT v_att.present THEN
                -- Absent → skip
                v_day := v_day + 1;
                CONTINUE;
            END IF;
            IF v_att.begin_time IS NOT NULL AND v_att.end_time IS NOT NULL THEN
                -- Ore reale din pontaj (UTC naive → local)
                v_work_start := (v_att.begin_time AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Bucharest';
                v_work_end   := (v_att.end_time   AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Bucharest';
            ELSE
                -- Prezent fara ore → fallback la program departament
                SELECT start_time, end_time INTO v_sched
                  FROM department_schedule
                 WHERE department = p_dept
                   AND weekday = EXTRACT(ISODOW FROM v_day)::smallint
                   AND active = true;
                IF NOT FOUND THEN
                    v_day := v_day + 1;
                    CONTINUE;
                END IF;
                v_work_start := v_day::timestamp + v_sched.start_time;
                v_work_end   := v_day::timestamp + v_sched.end_time;
            END IF;
        ELSE
            -- Nicio inregistrare → fallback la program departament (presupunem prezent daca weekday activ)
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
            v_work_start := v_day::timestamp + v_sched.start_time;
            v_work_end   := v_day::timestamp + v_sched.end_time;
        END IF;

        v_ov_start := GREATEST(v_work_start, v_start_local);
        v_ov_end   := LEAST(v_work_end, v_end_local);
        IF v_ov_end > v_ov_start THEN
            v_total := v_total + EXTRACT(EPOCH FROM (v_ov_end - v_ov_start)) / 60.0;
        END IF;

        v_day := v_day + 1;
    END LOOP;

    RETURN v_total;
END;
$$ LANGUAGE plpgsql STABLE;
