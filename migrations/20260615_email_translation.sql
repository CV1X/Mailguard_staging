-- v0.35.0 — Traducere emailuri in romana (manual + cache). Aditiv / idempotent.
ALTER TABLE emails ADD COLUMN IF NOT EXISTS translation_status  varchar(20);
ALTER TABLE emails ADD COLUMN IF NOT EXISTS source_lang         varchar(16);
ALTER TABLE emails ADD COLUMN IF NOT EXISTS translated_subject  text;
ALTER TABLE emails ADD COLUMN IF NOT EXISTS translated_text     text;
ALTER TABLE emails ADD COLUMN IF NOT EXISTS translated_at       timestamptz;
ALTER TABLE emails ADD COLUMN IF NOT EXISTS translation_model   varchar(80);
ALTER TABLE emails ADD COLUMN IF NOT EXISTS translation_error   text;
