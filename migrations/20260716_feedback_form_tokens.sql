-- T4: Formular public de feedback — token unic per client/campanie
-- Idempotent. Fără date tranzacționale/secrete.

CREATE TABLE IF NOT EXISTS feedback_form_tokens (
    id            bigserial PRIMARY KEY,
    token         varchar(64) NOT NULL,
    campaign_id   bigint NOT NULL REFERENCES feedback_campaigns(id) ON DELETE CASCADE,
    client_id     bigint NOT NULL REFERENCES clients(id),
    month_key     varchar(7) NOT NULL,
    expires_at    timestamptz NOT NULL,
    used_at       timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_feedback_form_tokens_token
    ON feedback_form_tokens(token);

CREATE INDEX IF NOT EXISTS idx_feedback_form_tokens_campaign_client_month
    ON feedback_form_tokens(campaign_id, client_id, month_key);
