-- 2026-06-16 — Grupare manuala atasamente (v0.40.0). Aditiv, idempotent.
-- Un document logic poate fi trimis ca mai multe atasamente in acelasi email
-- (ex. talon MD fata+spate). grouped_into pe MEMBRU = id-ul randului PRIMAR.
ALTER TABLE document_extractions ADD COLUMN IF NOT EXISTS grouped_into bigint NULL;
CREATE INDEX IF NOT EXISTS idx_doc_ext_grouped_into
  ON document_extractions (grouped_into) WHERE grouped_into IS NOT NULL;
