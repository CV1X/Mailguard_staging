-- 2026-08-03: două corecții de STARE (nu de schemă) pentru modulul Productivitate,
-- necesare ca fixurile de cod din v0.68.6 să aibă efect și pe producție.
--
-- Nu se adaugă tabele sau coloane: ambele scriu în tabelul existent `settings`, respectiv
-- curăță `productivity_monthly_snapshot`. Fișierul există fiindcă release-ul duce pe prod DOAR
-- ce se află în migrations/ — o comandă rulată manual pe staging nu ajunge acolo.
--
-- ATENȚIE la idempotență: `scripts/migrate.sh` este ExecStartPre, deci rulează la FIECARE
-- restart, iar `_release_migrations` sare peste fișierele deja aplicate. Chiar și așa, ambele
-- blocuri de mai jos sunt scrise ca să fie inofensive dacă ar rula din nou — vezi gărzile.

-- ─────────────────────────────────────────────────────────────────────────────
-- 1) STOP la raportul lunar duplicat
--
-- Cauza (reparată în cod, v0.68.6): `INSERT INTO audit_log(action, user_id, ...)` — coloana se
-- numește `actor`. Eroarea de sintaxă lăsa tranzacția abortată, `_mark_sent()` eșua în cascadă,
-- iar cheia `productivity.last_monthly_sent` nu se scria NICIODATĂ. Cron-ul (la 5 min) nu avea
-- ce citi și retrimitea raportul la fiecare rulare — 5 emailuri duplicate pe staging, 03.08.
--
-- Codul e reparat, dar cheia lipsește și pe prod. Fără rândurile de mai jos, prima rulare de
-- după release ar trimite raportul încă o dată (o singură dată — apoi s-ar marca corect).
-- Le scriem preventiv pentru luna în curs.
--
-- `ON CONFLICT DO NOTHING`: dacă cheia există deja (trimitere corectă, sau altă lună), NU o
-- suprascriem. O migrație nu are ce căuta peste o stare mai nouă decât ea.
INSERT INTO settings (key, value, description, updated_by, updated_at)
VALUES (
    'productivity.last_monthly_sent',
    to_jsonb(to_char(CURRENT_DATE, 'YYYY-MM')),
    'Luna (YYYY-MM) pentru care s-a trimis ultimul raport lunar de productivitate. Gard anti-duplicat.',
    'migration_20260803',
    now()
)
ON CONFLICT (key) DO NOTHING;

-- Cheie NOUĂ, citită de `_recently_sent()` (a treia poartă din send_monthly_reports_if_due):
-- gard independent de eticheta de lună, ca o cheie lipsă/coruptă să nu mai deschidă calea
-- retrimiterii.
INSERT INTO settings (key, value, description, updated_by, updated_at)
VALUES (
    'productivity.last_monthly_sent_at',
    to_jsonb(now()::text),
    'Momentul exact al ultimei trimiteri a raportului lunar. Blochează retrimiterea sub 25 de zile.',
    'migration_20260803',
    now()
)
ON CONFLICT (key) DO NOTHING;

-- ─────────────────────────────────────────────────────────────────────────────
-- 2) Recalcularea snapshot-ului lunii în curs
--
-- Cauza (reparată în cod, v0.67.1): `department_report` considera „operator activ" doar pe cine
-- avea ≥1 zi `present=true` în pontaj. În primele zile ale lunii pontajul e aproape gol, deci
-- oricine era în concediu atunci ieșea COMPLET din calcul — nu doar din ore_disponibile, ci și
-- din ore_planificate și din lista de operatori. Pe 03.08 Suport 1 a ieșit 840h (5 oameni) în
-- loc de 1008h (6), Suport 2 672h în loc de 840h.
--
-- Snapshot-ul lunar e imutabil prin design (`_save_snapshot` folosește ON CONFLICT DO NOTHING),
-- ca un target emis să nu se schimbe retroactiv sub picioarele oamenilor. Consecința: pe prod
-- codul nou NU rescrie de la sine cifrele deja înghețate. Snapshot-ul trebuie șters o dată, ca
-- următoarea accesare a paginii să-l regenereze din logica reparată.
--
-- Ștergem DOAR luna în curs. Lunile încheiate rămân intacte: acolo cifrele sunt deja raportate
-- și comunicate, iar o recalculare ar rescrie istoria.
--
-- Garda `_release_migrations` (verificată de migrate.sh) previne re-rularea, dar adăugăm și o
-- gardă proprie în `settings`: dacă fișierul ar fi cumva reaplicat într-o lună ulterioară, un
-- DELETE necondiționat ar șterge targetele valide ale acelei luni.
DO $$
DECLARE
    _guard text := 'productivity.snapshot_reset_20260803';
    _n     integer := 0;
BEGIN
    IF EXISTS (SELECT 1 FROM settings WHERE key = _guard) THEN
        RAISE NOTICE 'snapshot reset 20260803: deja aplicat, sar peste';
        RETURN;
    END IF;

    DELETE FROM productivity_monthly_snapshot
    WHERE year  = EXTRACT(YEAR  FROM CURRENT_DATE)::int
      AND month = EXTRACT(MONTH FROM CURRENT_DATE)::int;
    GET DIAGNOSTICS _n = ROW_COUNT;

    INSERT INTO settings (key, value, description, updated_by, updated_at)
    VALUES (
        _guard,
        to_jsonb(json_build_object('deleted_rows', _n, 'at', now()::text)::text),
        'Marcaj one-shot: snapshot-ul lunii curente a fost șters pentru recalculare (fix v0.67.1).',
        'migration_20260803',
        now()
    )
    ON CONFLICT (key) DO NOTHING;

    RAISE NOTICE 'snapshot reset 20260803: % rânduri șterse (se regenerează la prima accesare)', _n;
END $$;
