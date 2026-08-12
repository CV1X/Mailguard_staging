-- Coloană pentru excluderea clienților parteneri/furnizori/automatizati din satisfacție
ALTER TABLE clients ADD COLUMN IF NOT EXISTS satisfaction_exclude BOOLEAN NOT NULL DEFAULT FALSE;
