-- 20260723_noreply_autoreply.sql
-- Auto-reply no-reply: config SMTP dedicat, blacklist dezabonare, token unsubscribe one-click.
-- Idempotent / aditiv.

-- Config SMTP dedicat no-reply (separat de feedback_email_config — cont diferit, scop diferit).
CREATE TABLE IF NOT EXISTS noreply_smtp_config (
    id             bigserial PRIMARY KEY,
    smtp_host      varchar(255) NOT NULL,
    smtp_port      integer NOT NULL DEFAULT 587,
    smtp_user      varchar(255) NOT NULL,
    smtp_pass_enc  text NOT NULL,
    from_address   varchar(255) NOT NULL DEFAULT 'no-reply@cargotrack.ro',
    use_tls        boolean NOT NULL DEFAULT true,
    updated_at     timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_noreply_smtp_config_singleton ON noreply_smtp_config((true));

-- Blacklist: adrese care NU primesc auto-reply (dezabonare sau adăugate manual).
CREATE TABLE IF NOT EXISTS noreply_blacklist (
    id        bigserial PRIMARY KEY,
    email     varchar(320) NOT NULL,
    added_at  timestamptz NOT NULL DEFAULT now(),
    added_by  varchar(100),
    reason    varchar(100) DEFAULT 'unsubscribe'
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_noreply_blacklist_email ON noreply_blacklist(lower(email));

-- Token unsubscribe one-click (UUID în link-ul din email).
CREATE TABLE IF NOT EXISTS noreply_unsubscribe_tokens (
    token      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email      varchar(320) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    used_at    timestamptz
);
CREATE INDEX IF NOT EXISTS idx_noreply_unsub_tokens_email ON noreply_unsubscribe_tokens(email);

-- Marcaj pe emails: a fost trimis auto-reply?
ALTER TABLE emails ADD COLUMN IF NOT EXISTS autoreply_sent_at timestamptz;
CREATE INDEX IF NOT EXISTS idx_emails_autoreply_sent ON emails(autoreply_sent_at) WHERE autoreply_sent_at IS NOT NULL;
