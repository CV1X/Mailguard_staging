-- T1: Configurare KPI & scală — fundația modulului Feedback clienți
-- Idempotent. Fără date tranzacționale/secrete.

CREATE TABLE IF NOT EXISTS feedback_kpis (
    id               bigserial PRIMARY KEY,
    key              varchar(60) NOT NULL,
    name             varchar(120) NOT NULL,
    description      text,
    scale_max        smallint NOT NULL DEFAULT 5,
    comment_enabled  boolean NOT NULL DEFAULT true,
    comment_label    varchar(200),
    sort_order       int NOT NULL DEFAULT 0,
    active           boolean NOT NULL DEFAULT true,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT chk_feedback_kpis_scale_max CHECK (scale_max BETWEEN 2 AND 10)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_feedback_kpis_key
    ON feedback_kpis(key);

CREATE INDEX IF NOT EXISTS idx_feedback_kpis_active
    ON feedback_kpis(active)
    WHERE active = true;

-- Structură pregătită pentru rankinguri dinamice (agregare pe KPI, în timp).
-- Populată de T2 (campanii) / T4 (formular); citită de T7 (dashboard).
CREATE TABLE IF NOT EXISTS feedback_kpi_ratings (
    id               bigserial PRIMARY KEY,
    kpi_id           bigint NOT NULL REFERENCES feedback_kpis(id) ON DELETE CASCADE,
    client_id        bigint REFERENCES clients(id),
    campaign_id      bigint,
    rating           smallint NOT NULL,
    comment          text,
    submitted_at     timestamptz NOT NULL DEFAULT now(),
    created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_feedback_kpi_ratings_kpi_id
    ON feedback_kpi_ratings(kpi_id);

CREATE INDEX IF NOT EXISTS idx_feedback_kpi_ratings_client_id
    ON feedback_kpi_ratings(client_id);

CREATE INDEX IF NOT EXISTS idx_feedback_kpi_ratings_submitted_at
    ON feedback_kpi_ratings(submitted_at);

-- Seed KPI-uri implicite din context (suport, promptitudine, telematică) — doar dacă tabela e goală.
INSERT INTO feedback_kpis (key, name, description, scale_max, sort_order)
SELECT * FROM (VALUES
    ('suport', 'Suport clienți', 'Cât de mulțumit ești de răspunsul echipei de suport?', 5, 1),
    ('promptitudine', 'Promptitudine', 'Cât de rapid ai primit un răspuns la solicitarea ta?', 5, 2),
    ('telematica', 'Telematică', 'Cât de mulțumit ești de funcționarea serviciului de telematică?', 5, 3)
) AS seed(key, name, description, scale_max, sort_order)
WHERE NOT EXISTS (SELECT 1 FROM feedback_kpis);

-- Setare globală: scală implicită + comentariu implicit, folosită ca fallback de T4.
INSERT INTO settings (key, value)
VALUES ('feedback.defaults', '{"scale_max": 5, "comment_enabled": true, "comment_label": "Adaugă un comentariu (opțional)"}'::jsonb)
ON CONFLICT (key) DO NOTHING;
