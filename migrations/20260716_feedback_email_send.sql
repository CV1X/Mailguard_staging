-- T5: Trimitere emailuri campanie + tracking (deschideri / click / răspuns)
-- Idempotent. Parola SMTP se stochează criptată (credential_crypto.encrypt_credentials),
-- niciodată în clar în această tabelă.

CREATE TABLE IF NOT EXISTS feedback_email_config (
    id             bigserial PRIMARY KEY,
    smtp_host      varchar(255) NOT NULL,
    smtp_port      integer NOT NULL DEFAULT 587,
    smtp_user      varchar(255) NOT NULL,
    smtp_pass_enc  text NOT NULL,
    from_address   varchar(255) NOT NULL,
    use_tls        boolean NOT NULL DEFAULT true,
    updated_at     timestamptz NOT NULL DEFAULT now()
);

-- Config unică (single-row) — la fel ca alte tabele globale de configurare din proiect.
CREATE UNIQUE INDEX IF NOT EXISTS idx_feedback_email_config_singleton
    ON feedback_email_config((true));

-- Tracking per token: cine a fost trimis efectiv, cine a deschis (pixel/click), și pe ce canal.
ALTER TABLE feedback_form_tokens ADD COLUMN IF NOT EXISTS sent_at timestamptz;
ALTER TABLE feedback_form_tokens ADD COLUMN IF NOT EXISTS send_error varchar(300);
ALTER TABLE feedback_form_tokens ADD COLUMN IF NOT EXISTS opened_at timestamptz;
ALTER TABLE feedback_form_tokens ADD COLUMN IF NOT EXISTS opened_via varchar(20);

CREATE INDEX IF NOT EXISTS idx_feedback_form_tokens_sent_at
    ON feedback_form_tokens(sent_at);
