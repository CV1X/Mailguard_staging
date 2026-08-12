-- Retroactiv (2026-07-02): fișier lipsă pentru o migrație deja aplicată manual pe producție
-- înainte să existe fișierul în migrations/. Schema e deja prezentă pe staging (idempotent,
-- fără efect) — scopul e doar aliniere cu istoricul de migrații de pe producție.
ALTER TABLE attachments ADD COLUMN IF NOT EXISTS content_id TEXT;
ALTER TABLE attachments ADD COLUMN IF NOT EXISTS is_inline  BOOLEAN NOT NULL DEFAULT false;
