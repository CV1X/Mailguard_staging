-- Indexuri pentru filtrele paginii Task-uri (perioada + utilizator).
--
-- Context: odata cu v0.63.0 filtrul de ingestie s-a schimbat de la "allowlist de categorii" la
-- "asignat unui angajat din roster", iar tabela a crescut de la ~30k la ~69k randuri. In plus,
-- filtrul de utilizator (assignee_raw) e nou in UI. Fara indexurile de mai jos, lista facea sort
-- pe ~36k randuri (62ms si in crestere); cu ele, o cerere filtrata pe utilizator + luna e ~5ms.
--
-- Aditiv si idempotent. CONCURRENTLY nu poate rula in tranzactie -- daca runner-ul de migratii
-- porneste una implicita, scoate CONCURRENTLY (tabela e mica, lock-ul e de ordinul secundelor).

CREATE INDEX IF NOT EXISTS ix_ctgt_cts_created_at
    ON cts_task_ground_truth (cts_created_at);

CREATE INDEX IF NOT EXISTS ix_ctgt_assignee_raw
    ON cts_task_ground_truth (assignee_raw);
