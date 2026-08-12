-- OPS-2026-0122: mapare tip document local -> template IRIS (pt /documents/extract).
-- Aditiv, idempotent. Cargo360 ramane sursa de adevar; IRIS importa si intoarce id-uri.
ALTER TABLE document_types ADD COLUMN IF NOT EXISTS iris_template_id bigint;
ALTER TABLE document_types ADD COLUMN IF NOT EXISTS iris_synced_at timestamptz;
CREATE INDEX IF NOT EXISTS document_types_iris_tpl_idx ON document_types(iris_template_id);

-- setari pt modul (motor extractie + ultimul rezultat sync). Tabela settings = KV (key/value jsonb-ish).
INSERT INTO settings(key, value)
  VALUES ('doc_extract.engine', '"local"')
  ON CONFLICT (key) DO NOTHING;
INSERT INTO settings(key, value)
  VALUES ('doc_sync.last_result', '{}')
  ON CONFLICT (key) DO NOTHING;
