-- Matching apel<->client pe cheie canonică de telefon (ultimele 9 cifre).
--
-- Problema: clients.phones conține numere în formate eterogene ('0761134047',
-- '0037368295882'), iar calls.caller_number/callee_number în alte formate
-- ('+37368533883'). Matching-ul pe string exact (phones @> '["..."]') rata toate
-- numerele cu prefix diferit — în special MD/international (00 vs +).
--
-- Soluția: comparare pe ultimele 9 cifre. Fără index, expandarea jsonb_array_elements_text
-- peste 16k clienți face seq scan la fiecare apel (>120s pe backfill).
--
-- Tabelă derivată (nu index funcțional direct): un index pe expresie nu se poate crea peste
-- jsonb_array_elements_text, care e set-returning. Tabela se reconstruiește la fiecare sync
-- de clienți (vezi app/services/phone_match.rebuild_phone_index()).

CREATE TABLE IF NOT EXISTS client_phone_keys (
    client_id  BIGINT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    phone_key  VARCHAR(9) NOT NULL,
    PRIMARY KEY (client_id, phone_key)
);

CREATE INDEX IF NOT EXISTS idx_client_phone_keys_key ON client_phone_keys(phone_key);

-- Populare inițială (idempotent — ON CONFLICT DO NOTHING).
INSERT INTO client_phone_keys (client_id, phone_key)
SELECT c.id, right(regexp_replace(p, '\D', '', 'g'), 9)
FROM clients c, jsonb_array_elements_text(c.phones) p
WHERE length(regexp_replace(p, '\D', '', 'g')) >= 9
ON CONFLICT DO NOTHING;
