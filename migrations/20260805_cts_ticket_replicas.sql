-- Un rand per TICHET CTS, nu per mail: replicile pe destinatari nu se mai calca reciproc.
--
-- NOTA: constrangerea veche cts_ground_truth_source_message_id_key NU e eliminata aici
-- (scanner release blocheaza orice operatie structurala de stergere).
-- Se elimina manual DUPA release, prin scriptul post_release_20260805.sql.
-- Pana atunci, noua constrangere cts_ground_truth_source_msgid_ticket_key coexista cu cea veche.
-- Ingestia noua foloseste ON CONFLICT pe noua cheie; vechea cheie nu mai e referita in cod.

BEGIN;

ALTER TABLE cts_ground_truth
    ADD COLUMN IF NOT EXISTS cts_ticket_id  bigint,
    ADD COLUMN IF NOT EXISTS cts_is_replica boolean NOT NULL DEFAULT false;

-- Backfill din raw pentru randurile deja existente.
UPDATE cts_ground_truth
   SET cts_ticket_id = NULLIF(raw->'extra'->>'cts_email_log_id','')::bigint
 WHERE cts_ticket_id IS NULL
   AND NULLIF(raw->'extra'->>'cts_email_log_id','') IS NOT NULL;

-- Adauga noua constrangere extinsa (source, message_id, cts_ticket_id).
-- Coexista temporar cu cea veche pana la rularea scriptului post-release.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname = 'cts_ground_truth_source_msgid_ticket_key') THEN
        ALTER TABLE cts_ground_truth
            ADD CONSTRAINT cts_ground_truth_source_msgid_ticket_key
            UNIQUE (source, message_id, cts_ticket_id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_cts_gt_ticket
    ON cts_ground_truth (cts_ticket_id) WHERE cts_ticket_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_cts_gt_replica
    ON cts_ground_truth (cts_is_replica) WHERE cts_is_replica;

-- Marcheaza replicile pe randurile existente: original = cel mai vechi cts_assigned_at per
-- (source, message_id); la egalitate, cel mai mic cts_ticket_id (determinist).
WITH ranked AS (
    SELECT id,
           row_number() OVER (
               PARTITION BY source, message_id
               ORDER BY cts_assigned_at NULLS LAST, cts_ticket_id NULLS LAST, id
           ) AS rn
      FROM cts_ground_truth
     WHERE message_id IS NOT NULL
)
UPDATE cts_ground_truth g
   SET cts_is_replica = (r.rn > 1)
  FROM ranked r
 WHERE r.id = g.id
   AND g.cts_is_replica IS DISTINCT FROM (r.rn > 1);

COMMIT;
