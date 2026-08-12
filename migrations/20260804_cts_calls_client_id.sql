-- Clientul apelului CTS: sursa /cts/calls trimite `client_id` (= clients.iris_client_id) pentru
-- FIECARE apel, dar il pastram doar in `raw` si il foloseam exclusiv ca forward-fix pe
-- calls.client_id. Consecinta in UI (raportat 2026-08-04): apelurile CTS fara corespondent
-- While1 (call_local_id IS NULL) apareau cu client "—", desi clientul exista in sursa.
-- Verificat la 2026-08-04: 5.514 apeluri cu call_local_id NULL, TOATE cu client_id in raw.
--
-- Persistam client_id-ul CTS pe rand, ca lista sa il poata afisa independent de legatura While1.
-- Aditiv si idempotent.

ALTER TABLE cts_calls_ground_truth
    ADD COLUMN IF NOT EXISTS cts_client_id INTEGER;

COMMENT ON COLUMN cts_calls_ground_truth.cts_client_id IS
    'client_id din sursa CTS (= clients.iris_client_id). Independent de call_local_id.';

CREATE INDEX IF NOT EXISTS idx_cts_calls_gt_client
    ON cts_calls_ground_truth (cts_client_id)
    WHERE cts_client_id IS NOT NULL;

-- Backfill din `raw` pentru randurile deja sincronizate (sync-ul rolling acopera doar 72h).
UPDATE cts_calls_ground_truth
   SET cts_client_id = NULLIF(raw->>'client_id', '')::INTEGER
 WHERE cts_client_id IS NULL
   AND raw->>'client_id' IS NOT NULL
   AND raw->>'client_id' ~ '^[0-9]+$';
