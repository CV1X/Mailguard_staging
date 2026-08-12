-- 20260701_backfill_cts_solved_at.sql
-- FIX bug sync cts_solved_at (2026-07-01). Gateway-ul trimite momentul soluționării în
-- assignment.solved_at (+ top-level reply_at), NU la top-level solved_at/extra, deci
-- cts_groundtruth_sync._normalize_record lăsa cts_solved_at MEREU NULL. Codul e reparat
-- (citește acum assignment.solved_at); acest backfill repopulează rândurile EXISTENTE din
-- raw->assignment->>solved_at (fallback cts_reply_at). Idempotent (doar unde cts_solved_at IS NULL).
UPDATE cts_ground_truth
SET cts_solved_at = COALESCE(NULLIF(raw->'assignment'->>'solved_at','')::timestamptz, cts_reply_at)
WHERE cts_status = 'solved'
  AND cts_solved_at IS NULL
  AND (NULLIF(raw->'assignment'->>'solved_at','') IS NOT NULL OR cts_reply_at IS NOT NULL);
