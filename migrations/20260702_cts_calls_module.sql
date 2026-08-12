-- Modul "Apeluri CTS" — clasificare (categorie+stil) apeluri + comparatie cu CTS.
-- Aditiv, idempotent.

ALTER TABLE calls ADD COLUMN IF NOT EXISTS ai_tone varchar(20);

CREATE TABLE IF NOT EXISTS cts_calls_ground_truth (
  id                   bigserial PRIMARY KEY,
  call_local_id        bigint REFERENCES calls(id) ON DELETE SET NULL,
  cts_call_id          text,
  cts_category         varchar(32),
  cts_category_prev    varchar(32),
  cts_status           varchar(32),
  cts_assignee_email   varchar(320),
  cts_assignee_name    text,
  cts_assignee_id      integer,
  cts_assigned_at      timestamptz,
  cts_response_seconds integer,
  cts_started_at       timestamptz,
  cts_duration_seconds integer,
  changed_at           timestamptz,
  source               varchar(20) DEFAULT 'iris_sync',
  raw                  jsonb,
  fetched_at           timestamptz DEFAULT now(),
  last_synced_at       timestamptz,
  UNIQUE (source, cts_call_id)
);
CREATE INDEX IF NOT EXISTS idx_cts_calls_gt_call ON cts_calls_ground_truth(call_local_id);
CREATE INDEX IF NOT EXISTS idx_cts_calls_gt_assignee ON cts_calls_ground_truth (lower(cts_assignee_email)) WHERE cts_assignee_email IS NOT NULL;

CREATE TABLE IF NOT EXISTS ai_call_category_prompts (
  category      varchar(32) PRIMARY KEY,
  prompt_text   text,
  updated_at    timestamptz DEFAULT now(),
  updated_by    varchar(100)
);

CREATE TABLE IF NOT EXISTS ai_call_category_prompt_versions (
  id            bigserial PRIMARY KEY,
  category      varchar(32),
  prompt_text   text,
  source        varchar(20),
  created_at    timestamptz DEFAULT now(),
  created_by    varchar(100)
);
