-- Migrație: re-numerotare prioritate P0/P1 -> 1/2 + clients.email_priority
-- Idempotentă: re-rulabilă fără efecte secundare (UPDATE-urile sunt condiționate pe valorile vechi).
-- P0 (urgent) -> 1 ; P1 (normal) -> 2. Aceleași reguli, doar eticheta canonică se schimbă.

BEGIN;

-- 1. Snapshot backup (o singură dată)
CREATE TABLE IF NOT EXISTS _bak_ai_priority_20260625 AS
  SELECT id, ai_priority, ai_priority_result FROM emails;

CREATE TABLE IF NOT EXISTS _bak_ai_priority_corr_20260625 AS
  SELECT id, old_priority, new_priority FROM ai_priority_corrections;

-- 2. Remap emails.ai_priority
UPDATE emails SET ai_priority = '1' WHERE ai_priority = 'P0';
UPDATE emails SET ai_priority = '2' WHERE ai_priority = 'P1';

-- 3. Remap câmpul priority din ai_priority_result (jsonb)
UPDATE emails
   SET ai_priority_result = jsonb_set(ai_priority_result, '{priority}', '"1"')
 WHERE ai_priority_result ? 'priority' AND ai_priority_result->>'priority' = 'P0';
UPDATE emails
   SET ai_priority_result = jsonb_set(ai_priority_result, '{priority}', '"2"')
 WHERE ai_priority_result ? 'priority' AND ai_priority_result->>'priority' = 'P1';

-- 4. Remap corecțiile (learning)
UPDATE ai_priority_corrections SET old_priority = '1' WHERE old_priority = 'P0';
UPDATE ai_priority_corrections SET old_priority = '2' WHERE old_priority = 'P1';
UPDATE ai_priority_corrections SET new_priority = '1' WHERE new_priority = 'P0';
UPDATE ai_priority_corrections SET new_priority = '2' WHERE new_priority = 'P1';

-- 5. Clienți: coloană email_priority (1/2) adusă din IRIS
ALTER TABLE clients ADD COLUMN IF NOT EXISTS email_priority smallint;

COMMIT;

-- Verificare
SELECT 'emails' AS t, ai_priority, count(*) FROM emails GROUP BY 1,2 ORDER BY 2;
SELECT 'corr_old' AS t, old_priority, count(*) FROM ai_priority_corrections GROUP BY 1,2;
