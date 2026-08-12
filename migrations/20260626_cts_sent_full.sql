-- Mail-uri CTS: campuri aditive pentru emailul trimis complet (corp html, atasamente,
-- timestamp real, marcaj sters, cheie de thread). Sursa: feed CTS extins (outbox #9).
-- Strict aditiv + idempotent. Nu atinge tabela emails / zona Emailuri.
ALTER TABLE cts_ground_truth ADD COLUMN IF NOT EXISTS cts_reply_html  text;
ALTER TABLE cts_ground_truth ADD COLUMN IF NOT EXISTS cts_attachments jsonb;
ALTER TABLE cts_ground_truth ADD COLUMN IF NOT EXISTS cts_solved_at   timestamptz;
ALTER TABLE cts_ground_truth ADD COLUMN IF NOT EXISTS cts_deleted_at  timestamptz;
ALTER TABLE cts_ground_truth ADD COLUMN IF NOT EXISTS cts_thread_key  text;
CREATE INDEX IF NOT EXISTS idx_cts_gt_thread ON cts_ground_truth(cts_thread_key) WHERE cts_thread_key IS NOT NULL;
