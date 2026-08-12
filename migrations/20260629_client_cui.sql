-- OPS-2026-0122/0124: CUI-ul clientului adus din CTS, O SINGURA DATA pe client (nu per contract).
-- Validarea contractelor foloseste clients.cui (apartenenta la client) + client_contracts.contract_no
-- (numarul contractului). Aditiv + idempotent. Inert pana IRIS expune campul.
ALTER TABLE clients ADD COLUMN IF NOT EXISTS cui text;
CREATE INDEX IF NOT EXISTS clients_cui_idx ON clients(cui) WHERE cui IS NOT NULL;
