-- Antivirus / scanare fișiere — backward-compatible.
ALTER TABLE attachments ADD COLUMN IF NOT EXISTS scan_verdict TEXT;     -- clean|suspicious|malware|unscannable
ALTER TABLE attachments ADD COLUMN IF NOT EXISTS scan_threats JSONB;
ALTER TABLE attachments ADD COLUMN IF NOT EXISTS scanned_at   TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_attachments_scan_verdict ON attachments(scan_verdict)
    WHERE scan_verdict IS NOT NULL AND scan_verdict <> 'clean';

-- Politica antivirus (editabilă din UI).
INSERT INTO settings(key, value)
VALUES ('av_policy', '{
  "enabled": true,
  "malware_action": "quarantine_strict",
  "suspicious_score": 20
}'::jsonb)
ON CONFLICT (key) DO NOTHING;
