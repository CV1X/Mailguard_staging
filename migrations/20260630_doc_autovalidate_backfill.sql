-- OPS-2026-0122: paritate schema. Coloanele auto_validated / auto_validated_at / completeness_score
-- sunt folosite de cod (_maybe_auto_validate, _completeness_score) dar au fost aplicate ad-hoc pe
-- staging, fara fisier de migratie. Backfill idempotent pt paritate cu productia. Tipuri identice cu
-- staging: auto_validated boolean DEFAULT false, auto_validated_at timestamptz, completeness_score numeric(4,3).
ALTER TABLE document_extractions ADD COLUMN IF NOT EXISTS auto_validated     boolean DEFAULT false;
ALTER TABLE document_extractions ADD COLUMN IF NOT EXISTS auto_validated_at  timestamptz;
ALTER TABLE document_extractions ADD COLUMN IF NOT EXISTS completeness_score numeric(4,3);
