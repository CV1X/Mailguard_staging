-- OPS-2026-0124 (activare) — coloana categorie contract din CTS.
-- IRIS expune acum pe /clients/contact-list?include=vehicles,contracts campul
-- "categorie" la contracte (ex. "01. Monitorizare", "21. Recuperare Accize").
-- Aditiv + idempotent.
ALTER TABLE client_contracts ADD COLUMN IF NOT EXISTS category text;
CREATE INDEX IF NOT EXISTS client_contracts_category_idx ON client_contracts(lower(COALESCE(category, '')));
