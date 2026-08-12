-- Anti-spoofing (SPF/DKIM/DMARC enforcement) — backward-compatible.
-- Stochează verdictul de autentificare per email + politica configurabilă.

ALTER TABLE emails ADD COLUMN IF NOT EXISTS auth_verdict TEXT;       -- pass|suspicious|fail
ALTER TABLE emails ADD COLUMN IF NOT EXISTS auth_result  JSONB;      -- {spf,dkim,dmarc,score,reasons,...}

CREATE INDEX IF NOT EXISTS idx_emails_auth_verdict ON emails(auth_verdict)
    WHERE auth_verdict IS NOT NULL;

-- Politica de autentificare (editabilă din UI). Default conservator:
--  enabled=true; spoofing-ul domeniilor de încredere (impersonare) → carantină strictă;
--  spoofing extern (DMARC fail pe alt domeniu) → DOAR scor aditiv (NU carantină automată,
--  ca să nu prindem expeditori legitimi prost configurați); whitelist-ul manual e respectat.
INSERT INTO settings(key, value)
VALUES ('auth_policy', '{
  "enabled": true,
  "fail_action": "quarantine_strict",
  "escalate_external_fail": false,
  "protect_domains": [],
  "weights": {"dmarc_fail": 45, "spf_hardfail": 25, "spf_softfail": 8, "dkim_fail": 15,
              "no_auth_results": 6, "from_unaligned": 20, "returnpath_mismatch": 12},
  "suspicious_at": 12,
  "fail_at": 30
}'::jsonb)
ON CONFLICT (key) DO NOTHING;
