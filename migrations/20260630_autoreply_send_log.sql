-- 20260630_autoreply_send_log.sql
-- Faza 1 autoreply auto-send: jurnal decizii + fereastra anti-spam (throttle).
-- Idempotent / aditiv. In dry-run logam outcome='would_send' (fara trimitere reala);
-- randul 'would_send'/'sent' consuma fereastra de throttle per adresa expeditor.
CREATE TABLE IF NOT EXISTS autoreply_send_log (
  id             BIGSERIAL PRIMARY KEY,
  email_id       INTEGER,
  recipient      VARCHAR(320) NOT NULL,                       -- adresa careia i-am raspunde (from_address, lowercase)
  trigger        VARCHAR(24)  NOT NULL DEFAULT 'new_in_cts',  -- Faza 2: 'solved'
  outcome        VARCHAR(32)  NOT NULL,                       -- would_send | throttled | skipped_confidence | skipped_ineligible | sent | send_error
  reason         TEXT,
  confidence     REAL,
  suggested_text TEXT,
  send_mode      VARCHAR(16),                                 -- dry_run | cts_feed | graph
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_autoreply_send_log_recip_ts ON autoreply_send_log (recipient, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_autoreply_send_log_email    ON autoreply_send_log (email_id);
