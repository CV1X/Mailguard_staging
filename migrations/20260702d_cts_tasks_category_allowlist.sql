-- Seed settings['cts_tasks.category_allowlist']: categoriile de task ACCEPTATE la ingestie.
-- Confirmat de Razvan (2026-07-02): 398 categorii CTS total, covarsitor zgomot operational automat
-- (alerte echipamente, facturare, contracte). Doar acest subset tine de interactiune cu clientul.
-- Editabil din settings fara redeploy.
INSERT INTO settings(key, value) VALUES (
  'cts_tasks.category_allowlist',
  '["Message received from client", "Sesizare Telefonica", "Client call log - manually added", "Client contact email log", "Diverse", "Administrative"]'::jsonb
) ON CONFLICT (key) DO NOTHING;
