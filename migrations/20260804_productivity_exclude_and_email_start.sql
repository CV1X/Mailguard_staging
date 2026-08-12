-- Productivitate mailuri: (1) flag de excludere propriu, (2) documentarea sursei corecte de start.
--
-- ── (1) `clients.productivity_exclude` ────────────────────────────────────────────────────────
-- Entitățile care NU sunt clienți reali (sisteme automate de taxare, furnizori, pseudo-clienți
-- administrativi) intrau în calculul de productivitate: 179 din 972 de rânduri pe august 2026
-- (18%) — TOLL4EUROPE 74, HU-GO 36, RUPTELA 32, HELP DESK CTS 23, ORANGE 13, LOCATOR BG 1.
-- Apăreau în listă cu status „on time"/„overdue", deși nu reprezintă muncă de suport măsurabilă.
--
-- Flag SEPARAT de `satisfaction_exclude`, INTENȚIONAT. Cele două rapoarte răspund la întrebări
-- diferite („e clientul mulțumit?" vs „a răspuns operatorul în timp?"), iar cuplarea lor ar face
-- ca orice excludere viitoare dintr-unul să dispară silențios și din celălalt. Un client poate fi
-- legitim exclus din satisfacție și păstrat în productivitate.
--
-- Matching pe NUME (ILIKE), ca la `20260729i`: prinde automat variantele viitoare de același fel
-- (`HU-GO TEMP 2`, `RUPTELA BALTIC`) fără migrație nouă. Acoperă azi 10 clienți — `RUPTELA` și
-- `RUPTELA UAB` sunt înregistrări distincte.
--
-- ── (2) Sursa de start pentru durata mailurilor ───────────────────────────────────────────────
-- `cts_ground_truth.raw->'extra'->>'created_at'` NU e momentul intrării mailului în CTS: e
-- momentul creării TICHETULUI, adică momentul în care cineva atinge mailul. Se deplasează înainte
-- odată cu neglijarea mailului, deci întârzierea devine invizibilă prin construcție.
--   Ex. email_id 54196: primit 24.07 14:42, trimis în CTS 14:45, tichet creat 28.07 08:36
--   (4 zile mai târziu), rezolvat 29.07 06:55 — se raportau ~22h în loc de ~4.5 zile.
-- `raw->'extra'->>'email_date'` == `emails.received_at` exact, pe toate rândurile (acoperire 100%).
-- `emails.sent_to_cts_at` ar fi fost semantic corect, dar e NULL pe 2876/8648 rânduri (33%).
-- Codul (app/services/productivity.py, app/api/v1/productivity.py) trece pe `email_date`.
--
-- Idempotent: `ADD COLUMN IF NOT EXISTS` + `WHERE NOT productivity_exclude`.
-- Rollback: `UPDATE clients SET productivity_exclude = FALSE;` (coloana poate rămâne).

ALTER TABLE clients
    ADD COLUMN IF NOT EXISTS productivity_exclude BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN clients.productivity_exclude IS
    'Exclude mailurile/task-urile acestui client din calculul de productivitate. '
    'Independent de satisfaction_exclude — vezi migrations/20260804_productivity_exclude_and_email_start.sql';

CREATE INDEX IF NOT EXISTS idx_clients_productivity_exclude
    ON clients (id) WHERE productivity_exclude;

UPDATE clients SET productivity_exclude = TRUE, updated_at = NOW()
WHERE NOT productivity_exclude
  AND (
       name ILIKE 'HU-GO%'                 -- sisteme de taxare rutieră Ungaria (NÚSZ / hu-go.hu)
    OR name ILIKE 'LOCATOR BG%'            -- partener/integrator, nu client de suport
    OR name ILIKE 'RUPTELA%'               -- furnizor de dispozitive (RUPTELA + RUPTELA UAB)
    OR name ILIKE 'TOLL4EUROPE%'           -- sistem de taxare rutieră
    OR name ILIKE '00-FIRMA NECUNOSCUTA%'  -- placeholder de montaj, nu o firmă
    OR name ILIKE 'ORANGE ROMANIA%'        -- furnizor telecom (SIM/date), nu client de suport
    OR name ILIKE 'HELP DESK CTS%'         -- pseudo-client intern
    OR name ILIKE 'CTS INTERNAL%'          -- pseudo-client intern
  );

DO $$
DECLARE n INT; m INT;
BEGIN
    SELECT count(*) INTO n FROM clients WHERE productivity_exclude;
    SELECT count(*) INTO m FROM clients WHERE productivity_exclude AND NOT satisfaction_exclude;
    RAISE NOTICE 'clienti exclusi din productivitate: % (din care % NU erau exclusi din satisfactie)', n, m;
END $$;
