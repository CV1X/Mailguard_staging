-- OPS-2026-0124: VIN per vehicul (din CTS) pentru validarea CIV/COC fara numar de inmatriculare.
-- Aditiv, idempotent. ~30% din vehiculele CTS au VIN (restul null).
ALTER TABLE client_vehicles ADD COLUMN IF NOT EXISTS vin text;
CREATE INDEX IF NOT EXISTS client_vehicles_vin_idx ON client_vehicles(vin) WHERE vin IS NOT NULL;
