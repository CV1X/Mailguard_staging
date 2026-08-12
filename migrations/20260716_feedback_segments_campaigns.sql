-- T2: Segmente & campanii de feedback — targetare + eșantion lunar random
-- Idempotent. Fără date tranzacționale/secrete.

CREATE TABLE IF NOT EXISTS feedback_segments (
    id                  bigserial PRIMARY KEY,
    name                varchar(120) NOT NULL,
    description         text,
    satisfaction_min    numeric(5,2),
    satisfaction_max    numeric(5,2),
    exclude_partners    boolean NOT NULL DEFAULT true,
    active_clients_only boolean NOT NULL DEFAULT true,
    active              boolean NOT NULL DEFAULT true,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_feedback_segments_active
    ON feedback_segments(active)
    WHERE active = true;

CREATE TABLE IF NOT EXISTS feedback_campaigns (
    id              bigserial PRIMARY KEY,
    name            varchar(120) NOT NULL,
    segment_id      bigint NOT NULL REFERENCES feedback_segments(id) ON DELETE CASCADE,
    kpi_ids         jsonb NOT NULL DEFAULT '[]',
    sample_size     int NOT NULL DEFAULT 20,
    frequency       varchar(20) NOT NULL DEFAULT 'monthly',
    day_of_month    smallint NOT NULL DEFAULT 1,
    active          boolean NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT chk_feedback_campaigns_sample_size CHECK (sample_size > 0),
    CONSTRAINT chk_feedback_campaigns_day CHECK (day_of_month BETWEEN 1 AND 28),
    CONSTRAINT chk_feedback_campaigns_frequency CHECK (frequency IN ('monthly', 'on_demand'))
);

CREATE INDEX IF NOT EXISTS idx_feedback_campaigns_segment_id
    ON feedback_campaigns(segment_id);

CREATE INDEX IF NOT EXISTS idx_feedback_campaigns_active
    ON feedback_campaigns(active)
    WHERE active = true;

-- Eșantionul generat la fiecare rulare (audit + bază pentru T5 trimitere).
-- excluded_reason NULL = clientul e în eșantionul final; altfel motivul excluderii
-- (util pentru clienții candidați care au fost eliminați ÎNAINTE de random sampling).
CREATE TABLE IF NOT EXISTS feedback_campaign_samples (
    id                bigserial PRIMARY KEY,
    campaign_id       bigint NOT NULL REFERENCES feedback_campaigns(id) ON DELETE CASCADE,
    client_id         bigint NOT NULL REFERENCES clients(id),
    month_key         varchar(7) NOT NULL,
    excluded_reason   varchar(60),
    created_at        timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_feedback_campaign_samples_campaign_month
    ON feedback_campaign_samples(campaign_id, month_key);

CREATE UNIQUE INDEX IF NOT EXISTS idx_feedback_campaign_samples_unique_selected
    ON feedback_campaign_samples(campaign_id, client_id, month_key)
    WHERE excluded_reason IS NULL;
