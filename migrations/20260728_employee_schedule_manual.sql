-- 2026-07-28: Concedii manuale pe employee_schedule
-- Adaugă coloana entry_source pentru a diferenția intrările din CTS de cele adăugate manual.
-- Intrările CTS sunt șterse și re-inserate la fiecare sync; cele manuale supraviețuiesc.
ALTER TABLE employee_schedule ADD COLUMN IF NOT EXISTS entry_source text NOT NULL DEFAULT 'cts';
CREATE INDEX IF NOT EXISTS es_entry_source_idx ON employee_schedule(entry_source);
