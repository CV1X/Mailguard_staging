-- OPS-2026-0122: confidenta + metoda de EXTRAGERE (separat de confidence-ul de CLASIFICARE).
-- Folosite cand motorul de extragere = IRIS: raspunsul /documents/extract intoarce confidence/method.
-- Pastram confidence (clasificare) neatins ca sa nu stricam UI-ul / reclasificarea. Aditiv, idempotent.
ALTER TABLE document_extractions ADD COLUMN IF NOT EXISTS extract_confidence numeric(4,3);
ALTER TABLE document_extractions ADD COLUMN IF NOT EXISTS extract_method     varchar(20);

-- Flag: trimite si segmentele MULTI-PAGINA la IRIS (necesita endpoint IRIS multi-fisier, pages[]).
-- Ramane false pana IRIS suporta multi-fisier (outbox #16); pana atunci multi-pagina se extrage local.
INSERT INTO settings(key, value)
  VALUES ('doc_extract.iris_multifile', 'false')
  ON CONFLICT (key) DO NOTHING;
