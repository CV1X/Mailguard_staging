-- OPS-2026-0131 — Asignare pe utilizator (CTS): clasificator + statistici.
-- Aditiv/idempotent. Mirror al ai_department*.

ALTER TABLE emails
  ADD COLUMN IF NOT EXISTS ai_assignee        varchar(320),     -- email canonical (@cargotrack.ro) sau NULL = neasignat
  ADD COLUMN IF NOT EXISTS ai_assignee_result jsonb,
  ADD COLUMN IF NOT EXISTS ai_assignee_at     timestamptz,
  ADD COLUMN IF NOT EXISTS ai_assignee_manual boolean NOT NULL DEFAULT false;
CREATE INDEX IF NOT EXISTS idx_emails_ai_assignee ON emails (lower(ai_assignee)) WHERE ai_assignee IS NOT NULL;

ALTER TABLE cts_ground_truth
  ADD COLUMN IF NOT EXISTS cts_assignee_email varchar(320),
  ADD COLUMN IF NOT EXISTS cts_assignee_name  text,
  ADD COLUMN IF NOT EXISTS cts_assignee_id    integer,
  ADD COLUMN IF NOT EXISTS cts_assigned_at    timestamptz;
CREATE INDEX IF NOT EXISTS idx_cts_gt_assignee ON cts_ground_truth (lower(cts_assignee_email)) WHERE cts_assignee_email IS NOT NULL;

CREATE TABLE IF NOT EXISTS ai_assignee_corrections (
  id bigserial PRIMARY KEY,
  email_id bigint REFERENCES emails(id) ON DELETE CASCADE,
  old_assignee varchar(320),
  new_assignee varchar(320),
  old_reason text,
  corrected_by varchar(100),
  created_at timestamptz NOT NULL DEFAULT now());

-- Backfill din feed-ul deja stocat (raw->assignment), doar mail-uri primite.
UPDATE cts_ground_truth SET
  cts_assignee_email = NULLIF(raw->'assignment'->>'assignee_email',''),
  cts_assignee_name  = NULLIF(raw->'assignment'->>'assignee_name',''),
  cts_assignee_id    = NULLIF(raw->'assignment'->>'assignee_id','')::int,
  cts_assigned_at    = NULLIF(raw->'assignment'->>'assigned_at','')::timestamptz
WHERE raw ? 'assignment' AND COALESCE(cts_direction,'received')='received';
