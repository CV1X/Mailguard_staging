-- T3: Reguli generale de frecvență (anti-suprasolicitare) + opt-out
-- Transversal peste toate campaniile (T2). Idempotent. Fără date tranzacționale/secrete.

-- Ultima trimitere de feedback per client — transversal, indiferent de campanie.
ALTER TABLE clients ADD COLUMN IF NOT EXISTS feedback_last_sent_at timestamptz;

-- Opt-out manual (dezabonare) per client — transversal, indiferent de campanie.
ALTER TABLE clients ADD COLUMN IF NOT EXISTS feedback_opt_out boolean NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS idx_clients_feedback_last_sent_at
    ON clients(feedback_last_sent_at);

CREATE INDEX IF NOT EXISTS idx_clients_feedback_opt_out
    ON clients(feedback_opt_out)
    WHERE feedback_opt_out = true;

-- Fereastra minimă (luni) între două trimiteri către același client. Fallback la 6 dacă lipsește.
INSERT INTO settings (key, value)
VALUES ('feedback.frequency', '{"min_months_between_sends": 6}'::jsonb)
ON CONFLICT (key) DO NOTHING;
