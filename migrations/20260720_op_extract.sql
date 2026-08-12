-- Extragere serie OP din atașament — flux auxiliar routing departament
ALTER TABLE emails ADD COLUMN IF NOT EXISTS ai_op_series varchar(20);
ALTER TABLE emails ADD COLUMN IF NOT EXISTS ai_op_extract_attempts int DEFAULT 0;
ALTER TABLE emails ADD COLUMN IF NOT EXISTS ai_op_extract_at timestamptz;
CREATE INDEX IF NOT EXISTS idx_emails_pending_op
    ON emails(queue_status) WHERE queue_status = 'pending_op_extract';
