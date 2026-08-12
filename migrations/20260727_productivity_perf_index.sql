-- Fix performanță productivitate: index pe employee_attendance(employee_id, work_date)
-- Funcția business_minutes_emp() cauta pe (employee_id, work_date) fara index dedicat
-- -> zeci de mii de seq scan-uri la incarcare pagina Productivitate
CREATE INDEX IF NOT EXISTS employee_attendance_employee_id_work_date_idx
    ON employee_attendance(employee_id, work_date);
