-- Cargo360 — sistem de cozi pe pipeline (queue_status) + legatura ai_call_log->email
-- Data: 2026-06-11 · Autor cod: cristian-raul.covaci (CC) · Aprobare DDL: Andrei (Regula 14)
-- NEEXECUTAT pana la aprobare. Zero ALTER/DROP pe coloane existente; toate au DEFAULT.
-- emails.status ramane sursa de CLASIFICARE (clean/quarantined/quarantined_strict/ndr/released).
-- Spam NU are status propriu: e derivat din email_spam (override=TRUE sau spam_score>=50),
-- pe mailuri cu status=clean. queue_status modeleaza UNDE e mailul in procesare.

BEGIN;

-- 1) emails: stare in pipeline + flags operator/CTS
ALTER TABLE emails ADD COLUMN IF NOT EXISTS queue_status varchar(24) NOT NULL DEFAULT 'queued_general';
ALTER TABLE emails ADD COLUMN IF NOT EXISTS manual_clean boolean NOT NULL DEFAULT false;
ALTER TABLE emails ADD COLUMN IF NOT EXISTS sent_to_cts_at timestamptz;
ALTER TABLE emails ADD COLUMN IF NOT EXISTS cts_send_error text;
ALTER TABLE emails ADD COLUMN IF NOT EXISTS cts_send_attempts int NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_emails_queue_status ON emails(queue_status);

-- 2) ai_call_log: legatura cu emailul (singura coloana noua ceruta)
ALTER TABLE ai_call_log ADD COLUMN IF NOT EXISTS email_id bigint REFERENCES emails(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_ai_call_log_email ON ai_call_log(email_id);

-- 3) backfill queue_status coerent cu clasificarea curenta (one-shot, idempotent, in ORDINE de prioritate)
--    Carantina are PRIORITATE peste spam (decizie de securitate).
-- 3a) Carantina (simpla + stricta) -> terminal stopped_quarantine
UPDATE emails SET queue_status='stopped_quarantine'
  WHERE status IN ('quarantined','quarantined_strict');
-- 3b) NDR -> terminal (NU merge la CTS, NU se categoriseaza)
UPDATE emails SET queue_status='stopped_ndr' WHERE status='ndr';
-- 3c) Spam derivat (doar pe status=clean, neatins de 3a/3b) -> terminal stopped_spam
UPDATE emails e SET queue_status='stopped_spam'
  FROM email_spam s
  WHERE s.email_id=e.id AND e.queue_status='queued_general' AND e.status='clean'
    AND (s.override=TRUE OR s.spam_score>=50);
-- 3d) Clean/released deja livrate la FC ADMIN -> sent_to_cts (cu timestamp real daca exista)
UPDATE emails e SET queue_status='sent_to_cts', sent_to_cts_at=COALESCE(dq.delivered_at, now())
  FROM delivery_queue dq
  WHERE dq.email_id=e.id AND dq.delivered_to_admin=true
    AND e.queue_status='queued_general' AND e.status IN ('clean','released');
-- 3e) Restul clean/released (nelivrate inca) -> ready_for_cts
UPDATE emails SET queue_status='ready_for_cts'
  WHERE queue_status='queued_general' AND status IN ('clean','released');

COMMIT;

-- ROLLBACK (manual, daca e nevoie):
-- ALTER TABLE emails DROP COLUMN IF EXISTS queue_status, DROP COLUMN IF EXISTS manual_clean,
--   DROP COLUMN IF EXISTS sent_to_cts_at, DROP COLUMN IF EXISTS cts_send_error, DROP COLUMN IF EXISTS cts_send_attempts;
-- ALTER TABLE ai_call_log DROP COLUMN IF EXISTS email_id;
