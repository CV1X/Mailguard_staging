-- Cargo360 — Modul Procesare documente (Phase 1: fundatie)
-- Data: 2026-06-15 · Autor cod: cristian-raul.covaci (CC) · Regula 14: DDL aditiv pe DB-ul propriu.
-- Idempotent. Apply: docker exec -i <pg> psql -U mailguard -d mailguard < this_file.sql
-- Zero ALTER/DROP pe tabele existente. Rollback: DROP TABLE document_extractions, document_types;

BEGIN;

  -- Definitiile de tip de document (analog report_patterns, dar pe documente/atasamente).
  CREATE TABLE IF NOT EXISTS document_types (
    id              bigint PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    category        varchar(20)  NOT NULL,            -- 'vehicul' | 'sofer' | 'contract'
    name            varchar(160) NOT NULL,            -- ex: 'Talon', 'CIV', 'CEMT', 'Buletin'
    description     text,
    sample_path     text,                             -- cale fisier sablon pe disc
    sample_name     varchar(500),                     -- nume original
    sample_mime     varchar(200),
    extract_fields  jsonb NOT NULL DEFAULT '[]'::jsonb,   -- [{name,type,description}]
    extract_prompt  text,
    detect_prompt   text,                             -- (Phase 2) prompt de detectie/clasificare
    match_titles    jsonb NOT NULL DEFAULT '[]'::jsonb,   -- contracte: titluri de potrivire
    enabled         boolean NOT NULL DEFAULT true,
    status          varchar(20) NOT NULL DEFAULT 'active',  -- active | deleted
    created_by      varchar(160),
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz
  );
  CREATE UNIQUE INDEX IF NOT EXISTS uq_document_types_cat_name
    ON document_types (category, lower(name)) WHERE status = 'active';
  CREATE INDEX IF NOT EXISTS idx_document_types_category
    ON document_types (category) WHERE status = 'active';

  -- Rezultatele extragerii (populate in Phase 2; create acum ca fundatie).
  CREATE TABLE IF NOT EXISTS document_extractions (
    id               bigint PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    email_id         bigint REFERENCES emails(id) ON DELETE CASCADE,
    attachment_id    bigint REFERENCES attachments(id) ON DELETE CASCADE,
    document_type_id bigint REFERENCES document_types(id) ON DELETE SET NULL,
    category         varchar(20),
    detected_type    varchar(160),
    confidence       numeric(4,3),
    data             jsonb NOT NULL DEFAULT '{}'::jsonb,
    raw_text         text,
    method           varchar(30),                     -- pdf_text | ocr | vision
    model            varchar(80),
    status           varchar(24) NOT NULL DEFAULT 'pending',  -- pending|detected|extracted|error|sent_to_cts
    error            text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    extracted_at     timestamptz
  );
  CREATE UNIQUE INDEX IF NOT EXISTS uq_document_extractions_attachment
    ON document_extractions (attachment_id);
  CREATE INDEX IF NOT EXISTS idx_document_extractions_email
    ON document_extractions (email_id);
  CREATE INDEX IF NOT EXISTS idx_document_extractions_status
    ON document_extractions (status);

COMMIT;

SELECT 'migration 20260615_document_processing applied' AS status;
