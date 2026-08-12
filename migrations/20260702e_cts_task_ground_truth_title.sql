-- Titlu scurt (task_name, adesea trunchiat de CTS insusi) separat de continutul complet
-- (description, populat acum cu campul real `description` din payload, nu task_name).
ALTER TABLE cts_task_ground_truth ADD COLUMN IF NOT EXISTS title text;
