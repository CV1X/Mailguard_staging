-- 2026-07-03: extinde business_minutes() cu parametrul p_absent_dates date[] (implicit ARRAY[]).
-- Zilele din p_absent_dates sunt sarite din calculul SLA exact ca sarbatorile legale.
-- Backward-compatible: apelurile existente fara al 5-lea argument continua sa functioneze.
-- Folosit de productivity.py: fetch-urile de mail/task/device_ops trimit absenta individuala a
-- operatorului asignat, astfel incat SLA nu acumuleaza timp cat operatorul este absent.
CREATE OR REPLACE FUNCTION business_minutes(
    p_dept         text,
    p_start        timestamptz,
    p_end          timestamptz,
    p_holidays     date[] DEFAULT ARRAY[]::date[],
    p_absent_dates date[] DEFAULT ARRAY[]::date[]
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
    v_absent      date[];
    v_iter        integer := 0;
BEGIN
    IF p_start IS NULL OR p_end IS NULL OR p_end <= p_start THEN
        RETURN NULL;
    END IF;
    v_holidays := COALESCE(p_holidays,     ARRAY[]::date[]);
    v_absent   := COALESCE(p_absent_dates, ARRAY[]::date[]);
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

        IF v_day = ANY(v_absent) THEN
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
