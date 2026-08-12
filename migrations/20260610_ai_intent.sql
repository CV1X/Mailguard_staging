-- AI intent classification on emails (consumer of the IRIS AI channel).
-- Idempotent. Apply: docker exec -i <pg> psql -U mailguard -d mailguard < this_file.sql
ALTER TABLE emails ADD COLUMN IF NOT EXISTS ai_intent jsonb;
ALTER TABLE emails ADD COLUMN IF NOT EXISTS ai_intent_at timestamptz;
CREATE INDEX IF NOT EXISTS idx_emails_ai_intent ON emails USING gin(ai_intent);
SELECT 'migration 20260610_ai_intent applied' AS status;
