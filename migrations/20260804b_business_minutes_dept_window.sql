-- Durata pe ACOPERIREA DEPARTAMENTULUI, nu pe tura operatorului care a rezolvat.
--
-- PROBLEMA. `business_minutes_emp` prefera pontajul individual al operatorului. Daca mailul intra
-- inainte ca acel operator sa intre in tura, asteptarea nu se contoriza nicaieri.
--   Caz real (email_id 58516, Suport 1): mail intrat 03.08 09:56 local, rezolvat 13:16 de un
--   operator cu tura 12:30-21:00 => se numarau doar 46 min ("on time"), pentru o asteptare reala
--   de 3h20m. Cu programul departamentului (07:00-21:00): 199.7 min => overdue, corect.
--
-- REGULA (decizie de business, 2026-08-04): clientul asteapta DEPARTAMENTUL, nu persoana. Cat timp
-- departamentul are >=1 om prezent, timpul curge pe programul departamentului, indiferent cine
-- rezolva efectiv si in ce tura e.
--   - are `department_schedule` (suport_1/2/3, taxe_drum) -> fereastra = programul zilei
--   - nu are program (contabilitate, recuperare_tva)      -> fereastra = uniunea turelor celor
--     prezenti in acea zi (primul inceput -> ultimul final), din `employee_attendance`
--   - zi cu 0 prezenti -> nu curge deloc, se trece la ziua urmatoare
-- Intervalele care trec peste finalul programului continua a doua zi la deschidere (ex. intrat
-- 20:00, rezolvat 09:00 => 60 min azi + 120 min maine = 180 min).
--
-- SCOPE. Doar cele 6 departamente cerute explicit (`_DEPT_WINDOW_DEPARTMENTS`). Restul rămân pe
-- tura individuala, ca inainte -- schimbarea nu le atinge.
--
-- `employee_attendance.begin_time/end_time` sunt `timestamp WITHOUT time zone` in UTC. Verificat:
-- tura dominanta 05:00-13:30 = 08:00-16:30 local (activitatea reala incepe ~08:00), iar tura de
-- dupa-amiaza 09:30 = 12:30 local, cu 0 mailuri rezolvate inainte de 12:30 pe 408 de cazuri.
--
-- Oglindeste `_BizCache.business_minutes` / `_dept_window` din app/services/productivity.py --
-- orice schimbare aici trebuie facuta si acolo, altfel mailurile (Python) si task-urile (SQL) ar
-- raspunde diferit la aceeasi intrebare.
--
-- Idempotent: CREATE OR REPLACE. Rollback: se re-creeaza functia fara ramura de departament
-- (versiunea anterioara e in istoricul migratiilor).

CREATE OR REPLACE FUNCTION public.business_minutes_emp(
    p_dept text,
    p_employee_id integer,
    p_start timestamp with time zone,
    p_end timestamp with time zone,
    p_holidays date[] DEFAULT ARRAY[]::date[]
)
RETURNS numeric
LANGUAGE plpgsql
STABLE
AS $function$
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
    v_dept_window boolean;
    v_present_cnt integer;
BEGIN
    IF p_start IS NULL OR p_end IS NULL OR p_end <= p_start THEN
        RETURN NULL;
    END IF;
    v_holidays    := COALESCE(p_holidays, ARRAY[]::date[]);
    v_start_local := p_start AT TIME ZONE 'Europe/Bucharest';
    v_end_local   := p_end   AT TIME ZONE 'Europe/Bucharest';
    v_day         := v_start_local::date;
    v_last_day    := v_end_local::date;

    -- Departamentele care masoara pe acoperirea departamentului (vezi comentariul de sus).
    v_dept_window := p_dept IN ('suport_1','suport_2','suport_3','taxe_drum',
                                'contabilitate','recuperare_tva');

    WHILE v_day <= v_last_day AND v_iter < 731 LOOP
        v_iter := v_iter + 1;

        -- Sarbatoare legala → skip
        IF v_day = ANY(v_holidays) THEN
            v_day := v_day + 1;
            CONTINUE;
        END IF;

        IF v_dept_window THEN
            -- ── Fereastra DEPARTAMENTULUI ────────────────────────────────────────────────
            -- Zi cu 0 prezenti in departament = nu curge. Daca nu exista NICIO inregistrare
            -- de pontaj pentru ziua asta (pontaj neimportat / zi viitoare) nu penalizam:
            -- tratam ca zi potential lucratoare, ca in `is_working_day_for_dept`.
            SELECT count(*) FILTER (WHERE present) INTO v_present_cnt
              FROM employee_attendance
             WHERE department = p_dept AND work_date = v_day;

            IF v_present_cnt = 0 AND EXISTS (SELECT 1 FROM employee_attendance
                                              WHERE department = p_dept AND work_date = v_day) THEN
                v_day := v_day + 1;
                CONTINUE;
            END IF;

            SELECT start_time, end_time, requires_attendance INTO v_sched
              FROM department_schedule
             WHERE department = p_dept
               AND weekday = EXTRACT(ISODOW FROM v_day)::smallint
               AND active = true;

            IF FOUND THEN
                IF v_sched.requires_attendance AND v_present_cnt = 0 THEN
                    v_day := v_day + 1;
                    CONTINUE;
                END IF;
                v_work_start := v_day::timestamp + v_sched.start_time;
                v_work_end   := v_day::timestamp + v_sched.end_time;
            ELSE
                -- Fara program configurat: uniunea turelor reale ale celor prezenti.
                SELECT min((begin_time AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Bucharest'),
                       max((end_time   AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Bucharest')
                  INTO v_work_start, v_work_end
                  FROM employee_attendance
                 WHERE department = p_dept AND work_date = v_day AND present = true
                   AND begin_time IS NOT NULL AND end_time IS NOT NULL;

                IF v_work_start IS NULL OR v_work_end IS NULL THEN
                    v_day := v_day + 1;
                    CONTINUE;
                END IF;
            END IF;
        ELSE
            -- ── Comportament ANTERIOR: tura individuala a operatorului ───────────────────
            SELECT present, begin_time, end_time
              INTO v_att
              FROM employee_attendance
             WHERE employee_id = p_employee_id AND work_date = v_day;

            IF FOUND THEN
                IF NOT v_att.present THEN
                    v_day := v_day + 1;
                    CONTINUE;
                END IF;
                IF v_att.begin_time IS NOT NULL AND v_att.end_time IS NOT NULL THEN
                    v_work_start := (v_att.begin_time AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Bucharest';
                    v_work_end   := (v_att.end_time   AT TIME ZONE 'UTC') AT TIME ZONE 'Europe/Bucharest';
                ELSE
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
$function$;
