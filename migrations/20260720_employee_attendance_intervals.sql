-- 2026-07-20: coloana intervals pe employee_attendance
-- Stochează array-ul complet de perioade per angajat per zi (CTS trimite mai multe intervale).
-- Permite UI să afișeze toate perioadele în tooltip + suma corectă de minute.
ALTER TABLE employee_attendance ADD COLUMN IF NOT EXISTS intervals JSONB;
