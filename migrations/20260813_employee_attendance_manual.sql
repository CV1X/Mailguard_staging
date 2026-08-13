-- 2026-08-13: pontaj editat manual — nu se suprascrie la sync CTS.
--
-- Pe pagina Utilizatori → Pontaj pe departamente, un operator poate corecta
-- orele (ex. schimb 2 12:00–20:30 preluat greșit ca schimb 1). Rândurile cu
-- manual_override=true sunt sărite de pontaj_sync.sync_attendance().

ALTER TABLE employee_attendance
  ADD COLUMN IF NOT EXISTS manual_override BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS manual_override_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS manual_override_by TEXT;

CREATE INDEX IF NOT EXISTS employee_attendance_manual_override_idx
  ON employee_attendance(employee_id, work_date)
  WHERE manual_override = true;
