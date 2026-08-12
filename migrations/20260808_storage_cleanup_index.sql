-- Index pentru cleanup audio zilnic (WHERE transcript_status='success' AND audio_path IS NOT NULL AND created_at <)
CREATE INDEX IF NOT EXISTS idx_calls_audio_cleanup
    ON calls (created_at)
    WHERE transcript_status = 'success' AND audio_path IS NOT NULL;

-- Index pentru cleanup document_extractions (WHERE status != 'pending' AND created_at < CURRENT_DATE)
CREATE INDEX IF NOT EXISTS idx_doc_ext_cleanup
    ON document_extractions (created_at, status)
    WHERE status <> 'pending';
