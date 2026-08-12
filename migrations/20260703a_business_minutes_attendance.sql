-- 2026-07-03: business_minutes() extins cu prezenta reala din department_attendance.
-- Logica hibrid: daca exista rand in department_attendance pt (dept, zi) -> present controleaza;
-- daca nu exista -> fallback la comportamentul anterior (requires_attendance din department_schedule).
-- Aditiv + idempotent (CREATE OR REPLACE). Fara schimbari de schema.

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
    v_sched        RECORD;
    v_day_start    timestamp;
    v_day_end      timestamp;
    v_ov_start     timestamp;
    v_ov_end       timestamp;
    v_total        numeric := 0;
    v_holidays     date[];
    v_iter         integer := 0;
    v_has_pontaj   boolean;
    v_dept_present boolean;
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

        -- Reset per-iteratie (SELECT INTO nu reseteaza vars daca nu gaseste nimic in PL/pgSQL)
        v_has_pontaj   := NULL;
        v_dept_present := NULL;

        -- Logica hibrid prezenta: date reale pontaj au prioritate vs. requires_attendance
        SELECT true, present INTO v_has_pontaj, v_dept_present
          FROM department_attendance
          WHERE department = p_dept AND work_date = v_day
          LIMIT 1;

        IF v_has_pontaj IS NOT NULL THEN
            -- Exista rand in pontaj: present controleaza
            IF NOT v_dept_present THEN
                v_day := v_day + 1;
                CONTINUE;
            END IF;
        ELSIF v_sched.requires_attendance THEN
            -- Nu exista date pontaj dar ziua necesita confirmare: sari (comportament anterior)
            v_day := v_day + 1;
            CONTINUE;
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
