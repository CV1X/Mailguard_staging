-- Trasabilitate documente MailGuard -> CTS (CCTS-5308 / CCTS-5071)
--
-- Tabela e INTENTIONAT fara FK catre attachments/document_extractions/emails: acele randuri sunt
-- sterse de scripts/storage_cleanup.sh (zilnic, extractii procesate din zilele anterioare), iar
-- CTS anunta stergerile cu pana la o zi intarziere. Un FK ar face statistica sa dispara odata cu
-- sursa. Aici pastram doar ce trebuie pentru raport (nume, categorie, stare), nu documentul.

CREATE TABLE IF NOT EXISTS cts_document_tracking (
    id BIGSERIAL PRIMARY KEY,
    email_id BIGINT,
    attachment_id BIGINT NOT NULL,
    extraction_id BIGINT,
    attachment_name VARCHAR(500),
    document_type_id BIGINT,
    category VARCHAR(20),                             -- 'contract' | 'sofer' | 'vehicul'
    sent_to_cts_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    cts_status VARCHAR(20) NOT NULL DEFAULT 'sent',   -- sent -> saved|failed ; saved -> deleted
    cts_entity_type VARCHAR(20),                      -- tipul entitatii CTS pe care s-a atasat
    cts_entity_id BIGINT,                             -- id-ul entitatii CTS
    cts_fail_reason TEXT,
    cts_admin_id INT,                                 -- cine a sters in CTS (nullable)
    cts_deleted_at TIMESTAMPTZ,
    cts_retry_count INT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (attachment_id)
);

CREATE INDEX IF NOT EXISTS idx_cts_doc_tracking_status
    ON cts_document_tracking (cts_status);
CREATE INDEX IF NOT EXISTS idx_cts_doc_tracking_sent_at
    ON cts_document_tracking (sent_to_cts_at);
CREATE INDEX IF NOT EXISTS idx_cts_doc_tracking_category
    ON cts_document_tracking (category);
