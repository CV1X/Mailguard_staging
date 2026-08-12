-- OPS-2026-0122: marcaj explicit "doar identificare" pe tipul de document.
-- Sursa autoritara pentru "acest tip NU se trimite la IRIS pt extragere" (vs. doar emptiness of
-- extract_fields, care e fragil daca un admin adauga campuri informativ). Aditiv, idempotent.
ALTER TABLE document_types ADD COLUMN IF NOT EXISTS identify_only boolean NOT NULL DEFAULT false;
