-- Contract While1 confirmat de Razvan (2026-07-01): user_fullname (agent) e nume, nu extensie
-- (largim agent_extension); adaugam while1_uniqueid (legatura viitoare cu CTS: uniqueid ==
-- ctk_uniqueid), recording_ref (URL/id inregistrare capturat la ingest, folosit de call_audio.py),
-- call_status (ANSWERED/NOANSWER/BUSY/FAILED, ca sa sarim audio pentru apeluri fara inregistrare).
ALTER TABLE calls ALTER COLUMN agent_extension TYPE varchar(255);
ALTER TABLE calls ADD COLUMN IF NOT EXISTS while1_uniqueid varchar(255);
ALTER TABLE calls ADD COLUMN IF NOT EXISTS recording_ref text;
ALTER TABLE calls ADD COLUMN IF NOT EXISTS call_status varchar(20);
CREATE INDEX IF NOT EXISTS idx_calls_while1_uniqueid ON calls(while1_uniqueid);
