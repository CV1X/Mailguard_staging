-- 2026-07-02: modul "Device Operations" (Suport 2) -- tabela de ingestie, mirror pe
-- cts_task_ground_truth (modulul "Task-uri"). Sursa: IRIS Gateway /cts/device-operations
-- (cerut lui Razvan, outbox in asteptare la data acestei migratii -- vezi
-- docs/device_operations_endpoint_request.md). Coloanele urmeaza campurile propuse in cerere;
-- se pot ajusta printr-o migratie ulterioara daca Razvan confirma alt contract.
-- Aditiv + idempotent.

CREATE TABLE IF NOT EXISTS device_operations (
    id                    bigserial PRIMARY KEY,
    operation_id          text NOT NULL,
    action_type           text,
    status                text,
    client_id             bigint,
    client_name           text,
    assignee_raw          text,
    assignee_employee_id  bigint REFERENCES employee_department_mapping(id),
    department            text,
    device_serial         text,
    description           text,
    cts_created_at        timestamptz,
    cts_updated_at         timestamptz,
    source                varchar(20) DEFAULT 'iris_sync',
    raw_payload           jsonb,
    first_synced_at       timestamptz NOT NULL DEFAULT now(),
    last_synced_at        timestamptz NOT NULL DEFAULT now(),
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_device_operations_operation_id ON device_operations (operation_id);
CREATE INDEX IF NOT EXISTS ix_device_operations_status ON device_operations (status);
CREATE INDEX IF NOT EXISTS ix_device_operations_department ON device_operations (department);
CREATE INDEX IF NOT EXISTS ix_device_operations_action_type ON device_operations (action_type);
CREATE INDEX IF NOT EXISTS ix_device_operations_client_id ON device_operations (client_id);
CREATE INDEX IF NOT EXISTS ix_device_operations_assignee_employee_id ON device_operations (assignee_employee_id);
CREATE INDEX IF NOT EXISTS ix_device_operations_cts_updated_at ON device_operations (cts_updated_at);
