-- OPS-2026-0122: renamed_file — numele standardizat generat de AI pentru documentul extras
ALTER TABLE document_extractions
    ADD COLUMN IF NOT EXISTS renamed_file text;
