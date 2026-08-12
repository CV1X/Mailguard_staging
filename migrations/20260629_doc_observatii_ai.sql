-- OPS-2026-0125: observatii_ai — câmp text pentru notițe AI pe extracții documente
ALTER TABLE document_extractions
    ADD COLUMN IF NOT EXISTS observatii_ai text;
