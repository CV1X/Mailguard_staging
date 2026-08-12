-- IRIS Data Views — coloana auto_sync + interval
ALTER TABLE iris_dv_state ADD COLUMN IF NOT EXISTS auto_sync BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE iris_dv_state ADD COLUMN IF NOT EXISTS auto_sync_interval_minutes INTEGER NOT NULL DEFAULT 60;
