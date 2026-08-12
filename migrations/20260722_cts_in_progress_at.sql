-- Migratie: captare timestamp tranzitie in_progress pentru emailuri si task-uri
-- Scop: calcul time-to-claim (TTC) si time-to-solve (TTS) separat, in minute de lucru efectiv

-- 1. Coloana noua pe emailuri (cts_ground_truth)
ALTER TABLE cts_ground_truth
  ADD COLUMN IF NOT EXISTS cts_in_progress_at TIMESTAMPTZ;

-- 2. Coloana noua pe task-uri (cts_task_ground_truth)
ALTER TABLE cts_task_ground_truth
  ADD COLUMN IF NOT EXISTS cts_in_progress_at TIMESTAMPTZ;

-- 3. Backfill emailuri: cts_assigned_at e proxy fidel pentru momentul claimului
--    (vine din assignment.assigned_at din feed CTS, setat cand operatorul preia tichetul)
UPDATE cts_ground_truth
SET cts_in_progress_at = cts_assigned_at
WHERE cts_assigned_at IS NOT NULL
  AND cts_in_progress_at IS NULL;

-- 4. Index pe coloanele noi (folosite in calcule business_minutes_emp si filtre)
CREATE INDEX IF NOT EXISTS idx_cgt_in_progress_at
  ON cts_ground_truth(cts_in_progress_at)
  WHERE cts_in_progress_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_ctgt_in_progress_at
  ON cts_task_ground_truth(cts_in_progress_at)
  WHERE cts_in_progress_at IS NOT NULL;
