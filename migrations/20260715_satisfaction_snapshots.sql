-- T2: Snapshot lunar satisfacție per client
CREATE TABLE IF NOT EXISTS client_satisfaction_snapshots (
    id                   BIGSERIAL PRIMARY KEY,
    client_id            BIGINT NOT NULL REFERENCES clients(id),
    month_key            CHAR(7) NOT NULL,          -- 'YYYY-MM'
    satisfaction_pct     NUMERIC(5,2),
    is_unsatisfied       BOOLEAN,
    breakdown            JSONB,
    carry_forward        BOOLEAN NOT NULL DEFAULT FALSE,
    source_month_key     CHAR(7),                   -- luna din care a fost carry-forward-ată
    config_used          JSONB,
    computed_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_client_satisfaction_snapshots UNIQUE (client_id, month_key)
);

CREATE INDEX IF NOT EXISTS ix_client_satisfaction_snapshots_client_id
    ON client_satisfaction_snapshots (client_id);

CREATE INDEX IF NOT EXISTS ix_client_satisfaction_snapshots_month_key
    ON client_satisfaction_snapshots (month_key);
