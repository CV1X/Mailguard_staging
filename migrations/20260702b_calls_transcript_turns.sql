-- Ture de conversatie diarizate (AGENT/CLIENT) pentru afisare tip chat in CallDetail. Aditiv.
ALTER TABLE calls ADD COLUMN IF NOT EXISTS transcript_turns jsonb;
