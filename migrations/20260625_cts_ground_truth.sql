-- Retroactiv (2026-07-02): fișier lipsă pentru o migrație deja aplicată manual pe producție
-- înainte să existe fișierul în migrations/. Tabela e deja prezentă pe staging (idempotent,
-- fără efect) — scopul e doar aliniere cu istoricul de migrații de pe producție. Coloanele
-- adăugate ulterior (cts_assignee_*, cts_solved_at, cts_solved_seen_at etc.) au fiecare
-- propria migrație separată și nu sunt repetate aici.
CREATE TABLE IF NOT EXISTS cts_ground_truth (
  id               bigserial PRIMARY KEY,
  email_id         bigint,
  message_id       text,
  cts_category     varchar(32),
  cts_department   varchar(32),
  cts_reply_text   text,
  cts_reply_at     timestamptz,
  cts_status       varchar(32),
  source           varchar(20) DEFAULT 'iris_sync',
  raw              jsonb,
  fetched_at       timestamptz DEFAULT now(),
  UNIQUE (source, message_id)
);

CREATE INDEX IF NOT EXISTS idx_cts_gt_email   ON cts_ground_truth(email_id);
CREATE INDEX IF NOT EXISTS idx_cts_gt_msgid   ON cts_ground_truth(message_id);
CREATE INDEX IF NOT EXISTS idx_cts_gt_dept    ON cts_ground_truth(cts_department);
