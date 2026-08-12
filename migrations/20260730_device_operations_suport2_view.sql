-- 2026-07-30: sursa "Operatiuni" (Suport 2) trece de la /cts/device-operations (montatori)
-- la view_device_operations (Closed by/Closed at -- actorul Suport 2 care inchide operatia).
-- Vezi app/services/device_ops_suport2_sync.py.

ALTER TABLE device_operations ADD COLUMN IF NOT EXISTS closed_by_raw text;
ALTER TABLE device_operations ADD COLUMN IF NOT EXISTS closed_by_employee_id bigint
    REFERENCES employee_department_mapping(id);
ALTER TABLE device_operations ADD COLUMN IF NOT EXISTS closed_at timestamptz;
ALTER TABLE device_operations ADD COLUMN IF NOT EXISTS finished_at timestamptz;
ALTER TABLE device_operations ADD COLUMN IF NOT EXISTS operation_type_raw text;
ALTER TABLE device_operations ADD COLUMN IF NOT EXISTS dv_row_id text;

CREATE INDEX IF NOT EXISTS ix_device_operations_closed_by_employee_id ON device_operations (closed_by_employee_id);
CREATE INDEX IF NOT EXISTS ix_device_operations_closed_at ON device_operations (closed_at);
CREATE UNIQUE INDEX IF NOT EXISTS ux_device_operations_dv_row_id ON device_operations (dv_row_id) WHERE dv_row_id IS NOT NULL;
