-- Retroactiv (2026-07-02): fișier lipsă pentru o migrație deja aplicată manual pe producție
-- înainte să existe fișierul în migrations/. Schema e deja prezentă pe staging (idempotent,
-- fără efect) — scopul e doar aliniere cu istoricul de migrații de pe producție.
ALTER TABLE emails ADD COLUMN IF NOT EXISTS ai_autoreply             TEXT;
ALTER TABLE emails ADD COLUMN IF NOT EXISTS ai_autoreply_result      JSONB;
ALTER TABLE emails ADD COLUMN IF NOT EXISTS ai_autoreply_at          TIMESTAMPTZ;
ALTER TABLE emails ADD COLUMN IF NOT EXISTS ai_autoreply_status      VARCHAR(12);
ALTER TABLE emails ADD COLUMN IF NOT EXISTS ai_autoreply_confidence  REAL;

CREATE INDEX IF NOT EXISTS idx_emails_ai_autoreply_status ON emails(ai_autoreply_status);
