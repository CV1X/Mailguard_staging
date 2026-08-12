-- 2026-06-25: clients — add satisfaction_pct, purge inactive
ALTER TABLE clients ADD COLUMN IF NOT EXISTS satisfaction_pct NUMERIC(5,2);
-- Inactive clients with no linked emails can be deleted safely
DELETE FROM clients WHERE is_active = false
  AND NOT EXISTS (SELECT 1 FROM emails e WHERE e.client_id = clients.id);
