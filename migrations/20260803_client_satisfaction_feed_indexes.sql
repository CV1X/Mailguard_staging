-- Indexuri pentru feed-ul extern de satisfacție clienți (GET /api/v1/ext/clients/satisfaction).
--
-- Endpointul scanează `clients` (15.7k rânduri active) cu LEFT JOIN pe agregarea din
-- client_satisfaction_snapshots. Fără indexurile de mai jos, căutarea după nume face
-- seq scan + ILIKE pe 15.7k rânduri la fiecare pagină, iar ordonarea stabilă după
-- (name, id) sortează întreg setul.
--
-- Aditiv + idempotent. Nicio schemă modificată (doar indexuri).

-- 1) Căutare după nume (`q=...`, ILIKE '%text%'). Un btree clasic NU ajută la
--    pattern-uri care încep cu %; pg_trgm rezolvă exact acest caz.
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX IF NOT EXISTS idx_clients_name_trgm
    ON clients USING gin (name gin_trgm_ops);

-- 2) Ordonare stabilă pentru paginare keyset/offset: ORDER BY name ASC, id ASC.
CREATE INDEX IF NOT EXISTS idx_clients_name_id
    ON clients (name, id);

-- 3) Căutare după CUI cu normalizare (fără prefix RO, fără spații). Indexul existent
--    `clients_cui_idx` e pe valoarea brută; căutarea externă vine des ca "RO12345678"
--    sau "12345678" pentru același client, deci indexăm forma normalizată.
CREATE INDEX IF NOT EXISTS idx_clients_cui_normalized
    ON clients (upper(regexp_replace(coalesce(cui, ''), '[^0-9]', '', 'g')))
    WHERE cui IS NOT NULL;

-- 4) Agregarea per client (AVG + istoric) citește toate lunile unui client.
--    Index acoperitor: evită heap fetch pentru client_id/month_key/satisfaction_pct.
CREATE INDEX IF NOT EXISTS idx_css_client_month_pct
    ON client_satisfaction_snapshots (client_id, month_key)
    INCLUDE (satisfaction_pct, is_unsatisfied, carry_forward);
