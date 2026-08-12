-- IRIS Data Views — stare sincronizare per view
CREATE TABLE IF NOT EXISTS iris_dv_state (
    view_name        VARCHAR(120) PRIMARY KEY,
    etag             TEXT,
    cursor_val       TEXT,
    last_sync_at     TIMESTAMPTZ,
    last_error       TEXT,
    last_error_at    TIMESTAMPTZ,
    schema_version   INTEGER,
    prompt_version   INTEGER,
    total_rows       BIGINT,
    freshness_at     TIMESTAMPTZ,
    mode             VARCHAR(20),
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW()
);
