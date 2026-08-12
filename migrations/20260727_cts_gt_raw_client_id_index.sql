-- Index pe raw->'extra'->>'client_id' din cts_ground_truth.
-- Elimina seq scan (~40k rows) la fiecare client din lista/ClientDetail.
-- CONCURRENTLY = fara lock pe tabel (safe pe prod cu trafic live).
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_cts_gt_raw_client_id
ON cts_ground_truth ((raw->'extra'->>'client_id'))
WHERE raw->'extra'->>'client_id' IS NOT NULL;
