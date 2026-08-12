-- T1: Personal Mailbox Connect + Ingestie izolată
-- Izolat complet de tabelele CTS/emails. Rulabil idempotent.

CREATE TABLE IF NOT EXISTS personal_mailbox_accounts (
    id               bigserial PRIMARY KEY,
    user_id          bigint NOT NULL,
    label            text NOT NULL,
    imap_host        varchar(255) NOT NULL,
    imap_port        smallint NOT NULL DEFAULT 993,
    imap_ssl         boolean NOT NULL DEFAULT true,
    email_address    varchar(320) NOT NULL,
    cred_enc         text NOT NULL,
    status           varchar(30) NOT NULL DEFAULT 'pending_validation',
    last_error       text,
    last_poll_at     timestamptz,
    last_uid         bigint NOT NULL DEFAULT 0,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_pma_user_id
    ON personal_mailbox_accounts(user_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_pma_user_email
    ON personal_mailbox_accounts(user_id, email_address);

CREATE TABLE IF NOT EXISTS personal_mails (
    id               bigserial PRIMARY KEY,
    account_id       bigint NOT NULL REFERENCES personal_mailbox_accounts(id) ON DELETE CASCADE,
    user_id          bigint NOT NULL,
    imap_uid         bigint NOT NULL,
    message_id       text,
    from_address     text,
    subject          text,
    received_at      timestamptz,
    verdict          varchar(20) NOT NULL DEFAULT 'pending',
    verdict_reason   jsonb NOT NULL DEFAULT '[]',
    folder_action    varchar(20) NOT NULL DEFAULT 'none',
    folder_action_at timestamptz,
    created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_pm_account_uid
    ON personal_mails(account_id, imap_uid);

CREATE INDEX IF NOT EXISTS idx_pm_user_id
    ON personal_mails(user_id);

CREATE INDEX IF NOT EXISTS idx_pm_verdict_pending
    ON personal_mails(verdict)
    WHERE verdict = 'pending';
