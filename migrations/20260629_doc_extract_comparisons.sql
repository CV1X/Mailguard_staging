-- OPS-2026-0122: rezultate comparatie extractie locala vs IRIS (tab Comparatie IRIS).
-- Idempotent. Doar metadate de comparatie (nu inlocuieste document_extractions).
CREATE TABLE IF NOT EXISTS doc_extract_comparisons (
  id                       bigint PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
  extraction_attachment_id bigint,
  part_no                  int NOT NULL DEFAULT 0,
  type_id                  bigint,
  category                 varchar(20),
  type_name                varchar(160),
  local_data               jsonb,
  iris_data                jsonb,
  fields_total             int,
  fields_match             int,
  fields_diff              jsonb,
  local_conf               real,
  iris_conf                real,
  local_ms                 int,
  iris_ms                  int,
  local_method             varchar(20),
  iris_method              varchar(20),
  iris_error               text,
  created_by               varchar(160),
  created_at               timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS doc_cmp_cat_idx ON doc_extract_comparisons(category, created_at DESC);
CREATE INDEX IF NOT EXISTS doc_cmp_att_idx ON doc_extract_comparisons(extraction_attachment_id, part_no);
