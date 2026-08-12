-- Fix: coloana `source` era folosita in INSERT (cts_tasks_sync.py) dar lipsea din schema
-- initiala (20260702_cts_task_ground_truth.sql) -- omisa din greseala la scriere. Nu e cheie
-- de unicitate aici (iris_task_id e deja unic per-sursa CTS), doar bookkeeping/consistenta cu
-- restul modulelor cts_* (mirror pe cts_ground_truth.source).
ALTER TABLE cts_task_ground_truth ADD COLUMN IF NOT EXISTS source varchar(20) DEFAULT 'iris_sync';
