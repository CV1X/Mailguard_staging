-- Tracking corecturi operator pe documente — backward-compatible, idempotent.
-- corrected=true => la salvare operatorul a MODIFICAT date extrase sau a schimbat tipul
-- (distinct de simpla confirmare reviewed=true fără modificări).
ALTER TABLE document_extractions ADD COLUMN IF NOT EXISTS corrected    boolean NOT NULL DEFAULT false;
ALTER TABLE document_extractions ADD COLUMN IF NOT EXISTS corrected_at timestamptz;
CREATE INDEX IF NOT EXISTS idx_doc_ext_reviewed ON document_extractions(reviewed) WHERE reviewed;
