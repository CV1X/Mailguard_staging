-- Trasabilitate documente: corectii pe cts_document_tracking inainte de intrarea in productie.
--
-- (1) Cheia unica muta pe (attachment_id, part_no), simetric cu document_extractions.
--     Un atasament PDF poate contine MAI MULTE documente (contract + talon + act identitate);
--     acelea sunt randuri separate in document_extractions, distinse prin part_no, dar impart
--     acelasi attachment_id. Cu UNIQUE(attachment_id) toate s-ar fi contopit intr-un singur rand.
--     Masurat pe date reale (document_extractions_bak_sim20_20260630): 304 documente provenind din
--     226 atasamente — 78 de documente s-ar fi pierdut din statistica.
--
-- (2) Stare noua 'extracted': randul se creeaza la EXTRAGERE, nu doar la trimiterea spre CTS.
--     Altfel numitorul „cate documente s-au extras in total" ar fi trebuit citit din
--     document_extractions, care e golita zilnic de storage_cleanup.sh (0 randuri pe staging).
--     Ciclul de viata complet: extracted -> sent -> saved|failed ; saved -> deleted

ALTER TABLE cts_document_tracking
    ADD COLUMN IF NOT EXISTS part_no SMALLINT NOT NULL DEFAULT 0;

-- sent_to_cts_at devine nullable: un document 'extracted' care nu a plecat inca spre CTS nu are data.
ALTER TABLE cts_document_tracking
    ALTER COLUMN sent_to_cts_at DROP NOT NULL;
ALTER TABLE cts_document_tracking
    ALTER COLUMN sent_to_cts_at DROP DEFAULT;

-- Momentul extragerii (numitorul statisticii) — independent de momentul trimiterii.
ALTER TABLE cts_document_tracking
    ADD COLUMN IF NOT EXISTS extracted_at TIMESTAMPTZ NOT NULL DEFAULT now();

ALTER TABLE cts_document_tracking
    ALTER COLUMN cts_status SET DEFAULT 'extracted';

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_constraint
               WHERE conname = 'cts_document_tracking_attachment_id_key') THEN
        ALTER TABLE cts_document_tracking
            DROP CONSTRAINT cts_document_tracking_attachment_id_key;
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_cts_doc_tracking_att_part
    ON cts_document_tracking (attachment_id, part_no);

CREATE INDEX IF NOT EXISTS idx_cts_doc_tracking_extracted_at
    ON cts_document_tracking (extracted_at);
