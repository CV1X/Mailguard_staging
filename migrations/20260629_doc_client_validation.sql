-- OPS-2026-0122/0124: validare date extrase din documente vs. activele clientului (CTS)
-- Vehicul = match pe numarul de inmatriculare; contract = match pe serie/CUI (cand CTS le livreaza).
-- Aditiv + idempotent. Observatia (informativa) se scrie in document_extractions.observatii_ai
-- (deja livrat catre CTS de /cts/get_email_documents); aici stocam si un verdict structurat.

-- Verdict per extragere: match | mismatch | no_ref | no_key | no_client | pending
ALTER TABLE document_extractions ADD COLUMN IF NOT EXISTS client_match        varchar(16);
ALTER TABLE document_extractions ADD COLUMN IF NOT EXISTS client_match_detail text;
ALTER TABLE document_extractions ADD COLUMN IF NOT EXISTS client_match_at      timestamptz;
CREATE INDEX IF NOT EXISTS doc_ext_client_match_idx
    ON document_extractions(client_match) WHERE client_match IS NOT NULL;

-- Contracte: campuri aduse din CTS pentru validare (serie/numar contract + CUI client).
-- Inert pana cand IRIS extinde feed-ul /clients/contact-list?include=contracts (vezi outbox).
ALTER TABLE client_contracts ADD COLUMN IF NOT EXISTS contract_no text;
ALTER TABLE client_contracts ADD COLUMN IF NOT EXISTS cui         text;
CREATE INDEX IF NOT EXISTS client_contracts_contract_no_idx
    ON client_contracts(contract_no) WHERE contract_no IS NOT NULL;
CREATE INDEX IF NOT EXISTS client_contracts_cui_idx
    ON client_contracts(cui) WHERE cui IS NOT NULL;
