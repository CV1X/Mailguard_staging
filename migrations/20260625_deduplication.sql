-- Cargo360 — Deduplicare emailuri identice trimise multiplu în < 3 minute
-- Data: 2026-06-25 · Autor: cristian-raul.covaci (CC) · Regula 14 (DDL proprie aplicație)
-- Aditiv/idempotent: IF NOT EXISTS, niciun DROP, DEFAULT safe.

BEGIN;

-- 1) Coloana dedup_of: FK spre emailul original (cel mai timpuriu din grup)
ALTER TABLE emails ADD COLUMN IF NOT EXISTS dedup_of bigint REFERENCES emails(id) ON DELETE SET NULL;

-- 2) Index pentru căutarea rapidă la procesare (sender+subject+timp desc, exclude duplicate deja marcate)
CREATE INDEX IF NOT EXISTS idx_emails_dedup_lookup
    ON emails(from_address, subject, received_at DESC)
    WHERE status != 'duplicate';

-- 3) Index secundar pe dedup_of (pentru linkuri UI "duplicat al emailului X")
CREATE INDEX IF NOT EXISTS idx_emails_dedup_of ON emails(dedup_of) WHERE dedup_of IS NOT NULL;

COMMIT;

-- ROLLBACK (dacă e nevoie, fără impact functional):
-- ALTER TABLE emails DROP COLUMN IF EXISTS dedup_of;
-- DROP INDEX IF EXISTS idx_emails_dedup_lookup;
-- DROP INDEX IF EXISTS idx_emails_dedup_of;
