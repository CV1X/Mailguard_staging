-- 2026-07-02: contract CONFIRMAT de Razvan pt GET /cts/device-operations (LIVE).
-- CTS expune direct `terminal` (bool, dedus din finished_at/closed_at/canceled_at) si
-- `device_imei` (87% acoperire, complementar la device_serial 98%) -- coloane noi, aditive.
-- Vezi app/services/device_ops_sync.py pt normalizare.

ALTER TABLE device_operations ADD COLUMN IF NOT EXISTS terminal boolean;
ALTER TABLE device_operations ADD COLUMN IF NOT EXISTS device_imei text;

CREATE INDEX IF NOT EXISTS ix_device_operations_terminal ON device_operations (terminal);
