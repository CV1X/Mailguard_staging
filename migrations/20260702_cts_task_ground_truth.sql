-- Task-uri module: mirror ground-truth pt task-uri din CTS, sincronizat prin IRIS Gateway
-- GET /cts/tasks (endpoint inca neconstruit de IRIS la 2026-07-02 -- vezi OUTBOX_tasks_endpoint.md).
-- Tabela se creeaza acum ca aplicatia sa porneasca curat; ramane goala (sync esueaza gratios,
-- 404) pana IRIS expune endpoint-ul.

CREATE TABLE IF NOT EXISTS cts_task_ground_truth (
    id                    bigserial PRIMARY KEY,

    -- identificator IRIS -- cheia de idempotenta (ON CONFLICT), NU un id intern Cargo360
    iris_task_id          text NOT NULL,

    task_type             text,          -- text liber; enum CTS TBD (Razvan)
    status                text,          -- text liber; enum CTS TBD (Razvan)
    priority              text,

    -- assignee: valoare bruta + rezolvare locala best-effort
    assignee_raw          text,
    assignee_employee_id  bigint REFERENCES employee_department_mapping(id),

    -- legatura optionala cu mailul/apelul de origine, rezolvata prin cheie naturala
    source_message_id     text,
    email_id              bigint REFERENCES emails(id),
    source_call_ref        text,
    call_id                bigint REFERENCES calls(id),

    client_name            text,
    department              text,        -- cum vine de la CTS; NEFILTRAT pe VALID_DEPARTMENTS aici
    description             text,

    cts_created_at           timestamptz,
    cts_updated_at           timestamptz,  -- cursor de sync (mirror cts_ground_truth.updated_at)

    last_synced_at            timestamptz NOT NULL DEFAULT now(),
    first_synced_at           timestamptz NOT NULL DEFAULT now(),

    raw_payload                jsonb,       -- payload IRIS complet, pt corectii de mapare ulterioare

    created_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                 timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_cts_task_ground_truth_iris_task_id
    ON cts_task_ground_truth (iris_task_id);
CREATE INDEX IF NOT EXISTS ix_cts_task_ground_truth_cts_updated_at
    ON cts_task_ground_truth (cts_updated_at);
CREATE INDEX IF NOT EXISTS ix_cts_task_ground_truth_status
    ON cts_task_ground_truth (status);
CREATE INDEX IF NOT EXISTS ix_cts_task_ground_truth_department
    ON cts_task_ground_truth (department);
CREATE INDEX IF NOT EXISTS ix_cts_task_ground_truth_assignee_employee_id
    ON cts_task_ground_truth (assignee_employee_id);
CREATE INDEX IF NOT EXISTS ix_cts_task_ground_truth_email_id
    ON cts_task_ground_truth (email_id);
CREATE INDEX IF NOT EXISTS ix_cts_task_ground_truth_call_id
    ON cts_task_ground_truth (call_id);

-- Setari KV (sync tasks)
INSERT INTO settings(key, value) VALUES ('cts_tasks.sync_enabled', 'false'::jsonb) ON CONFLICT (key) DO NOTHING;
