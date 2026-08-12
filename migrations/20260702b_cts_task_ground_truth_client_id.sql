-- Follow-up la 20260702_cts_task_ground_truth.sql: /cts/tasks (deja live la IRIS!) trimite
-- client_id numeric (nu un nume), care se leaga de clients.iris_client_id (NU clients.id).
-- client_name text ramane in schema (poate fi populat manual/fallback), dar sursa reala de
-- adevar pt afisare e JOIN-ul pe client_id la nevoie (in router).
ALTER TABLE cts_task_ground_truth ADD COLUMN IF NOT EXISTS client_id bigint;
CREATE INDEX IF NOT EXISTS ix_cts_task_ground_truth_client_id ON cts_task_ground_truth (client_id);
