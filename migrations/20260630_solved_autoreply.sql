-- 20260630_solved_autoreply.sql
-- Faza 2 (DRY-RUN): reply automat la SOLVED + anti-spam.
-- Captureaza din feed-ul CTS optiunea "trimite mail automat la solved" si marcheaza tranzitia
-- in 'solved' ca sa declansam reply-ul de inchidere DOAR pe tranzitii noi (nu pe re-sync rolling,
-- nu pe backfill-ul istoric de ~4900 mailuri deja solved). Idempotent, aditiv, backward-compatible.
-- Jurnalul deciziilor (autoreply_send_log) + coloana `trigger` exista deja (20260630_autoreply_send_log.sql).

-- Optiunea din CTS (bifa operatorului). Default in CTS = bifat (auto). NULL = inca netrimisa de CTS.
--   TRUE / NULL -> eligibil pentru reply automat de inchidere;
--   FALSE       -> operatorul a raspuns manual (a selectat un template) -> NU trimitem.
ALTER TABLE cts_ground_truth ADD COLUMN IF NOT EXISTS cts_solved_auto_reply BOOLEAN;

-- Marcaj setat O SINGURA DATA, exact la trecerea statusului in 'solved' (mirror al lui changed_at).
-- Permite detectia tranzitiei in RETURNING fara a re-declansa pe re-sync-ul ferestrei rolling.
ALTER TABLE cts_ground_truth ADD COLUMN IF NOT EXISTS cts_solved_seen_at TIMESTAMPTZ;
