-- T1: Motor satisfacție — coloană breakdown per client
ALTER TABLE clients ADD COLUMN IF NOT EXISTS satisfaction_breakdown jsonb;
