-- Retroactiv (2026-07-02): fișier lipsă pentru o migrație deja aplicată manual pe producție
-- înainte să existe fișierul în migrations/. Schema e deja prezentă pe staging (idempotent,
-- fără efect) — scopul e doar aliniere cu istoricul de migrații de pe producție.
ALTER TABLE emails ADD COLUMN IF NOT EXISTS ai_priority         VARCHAR(8);
ALTER TABLE emails ADD COLUMN IF NOT EXISTS ai_priority_result  JSONB;
ALTER TABLE emails ADD COLUMN IF NOT EXISTS ai_priority_at      TIMESTAMPTZ;
ALTER TABLE emails ADD COLUMN IF NOT EXISTS ai_priority_manual  BOOLEAN DEFAULT false;

CREATE INDEX IF NOT EXISTS idx_emails_ai_priority ON emails(ai_priority);
