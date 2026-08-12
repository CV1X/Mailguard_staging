-- 2026-07-03: business_minutes() v4 -- fereastra reala din employee_attendance (primary).
-- Fallback: department_schedule (perioade istorice fara pontaj / date viitoare).
-- CREATE OR REPLACE: aditiv, idempotent, semnatura identica cu v1/v2/v3.

CREATE OR REPLACE FUNCTION business_minutes(
    p_dept     text,
    p_start    timestamptz,
    p_end      timestamptz,
    p_holidays date[] DEFAULT ARRAY[]::date[]
) RETURNS numeric AS $$
DECLARE
    v_start_local  timestamp;
    v_end_local    timestamp;
    v_day          date;
    v_last_day     date;
    v_day_start    timestamp;
    v_day_end      timestamp;
    v_ov_start     timestamp;
    v_ov_end       timestamp;
    v_total        numeric := 0;
    v_holidays     date[];
    v_iter         integer := 0;
    v_att_start    time;
    v_att_end      time;
    v_fb_start     time;
    v_fb_end       time;
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

        -- Reset per-iteratie
        v_att_start := NULL;
        v_att_end   := NULL;

        -- Primary: fereastra reala de prezenta (min intrare .. max iesire)
        SELECT min(begin_time)::time, max(end_time)::time
          INTO v_att_start, v_att_end
          FROM employee_attendance
          WHERE department = p_dept
            AND work_date = v_day
            AND present = true
            AND begin_time IS NOT NULL;

        IF v_att_start IS NULL THEN
            -- Fallback: department_schedule (date fara pontaj / perioade istorice)
            v_fb_start := NULL;
            v_fb_end   := NULL;
            SELECT start_time, end_time
              INTO v_fb_start, v_fb_end
              FROM department_schedule
              WHERE department = p_dept
                AND weekday = EXTRACT(ISODOW FROM v_day)::smallint
                AND active = true;
            IF v_fb_start IS NULL THEN
                v_day := v_day + 1;
                CONTINUE;
            END IF;
            v_att_start := v_fb_start;
            v_att_end   := v_fb_end;
        END IF;

        v_day_start := v_day::timestamp + v_att_start;
        v_day_end   := v_day::timestamp + v_att_end;
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
