-- Migrare Faza 1: persistare headere email + reputatie expeditori spam
-- Idempotentă (IF NOT EXISTS / ADD COLUMN IF NOT EXISTS)
-- Aplică: sudo docker exec -i $(docker ps --filter expose=5432 -q | head -1) psql -U mailguard -d mailguard < /opt/iris-mailguard/migrations/20260609_spam_phase1.sql

-- 1. Coloana email_headers pe tabelul emails (emailuri noi de la implementare incolo)
ALTER TABLE emails ADD COLUMN IF NOT EXISTS email_headers jsonb NOT NULL DEFAULT '{}';
CREATE INDEX IF NOT EXISTS idx_emails_headers ON emails USING gin(email_headers);

-- 2. Reputatie expeditori spam (allowlist / blocklist)
CREATE TABLE IF NOT EXISTS spam_sender_reputation (
    id BIGSERIAL PRIMARY KEY,
    scope_type VARCHAR(20) NOT NULL DEFAULT 'sender_exact',
    scope_value VARCHAR(320) NOT NULL,
    reputation VARCHAR(20) NOT NULL,
    created_by VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_action VARCHAR(20),
    action_count INT NOT NULL DEFAULT 1,
    CONSTRAINT uq_spam_rep UNIQUE (scope_type, scope_value)
);
CREATE INDEX IF NOT EXISTS idx_spam_rep_scope ON spam_sender_reputation(scope_type, scope_value);

-- 3. Log dezabonari one-click (audit + monitorizare)
CREATE TABLE IF NOT EXISTS spam_unsubscribe_log (
    id BIGSERIAL PRIMARY KEY,
    email_id BIGINT REFERENCES emails(id),
    from_address VARCHAR(320),
    method VARCHAR(20),
    url TEXT,
    http_status INT,
    success BOOLEAN,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

SELECT 'Migration 20260609_spam_phase1 applied OK' AS status;
