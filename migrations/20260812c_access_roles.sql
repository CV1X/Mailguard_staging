-- v2.5.0 — Roluri interne de acces (operator / admin / developer)
-- Independent de CTS/Cargo360: rolul se seteaza manual din Utilizatori -> Roluri acces,
-- NU se deduce din cts_dv_employee.seniority (numeric 1-5, gol la ~54% din angajati).
-- Idempotent + aditiv.

ALTER TABLE admin_users
    ADD COLUMN IF NOT EXISTS access_role varchar(20) NOT NULL DEFAULT 'operator';

-- Deny-by-default: userii noi (inclusiv cei provizionati prin IRIS SSO) intra 'operator'.
-- Seed explicit pentru conturile stabilite de Razvan.
UPDATE admin_users SET access_role = 'developer'
 WHERE lower(email) IN ('razvan.perticas@cargotrack.ro', 'raul.covaci@trakosoft.ro')
   AND access_role <> 'developer';

UPDATE admin_users SET access_role = 'admin'
 WHERE lower(email) IN ('bianca.judea@cargotrack.ro',
                        'robert.kovacs@cargotrack.ro',
                        'calin.lucaciu@cargotrack.ro')
   AND access_role <> 'admin';

-- Constraint idempotent: recreat ca sa fie sigur consistent intre staging si prod.
ALTER TABLE admin_users DROP CONSTRAINT IF EXISTS admin_users_access_role_chk;
ALTER TABLE admin_users ADD CONSTRAINT admin_users_access_role_chk
    CHECK (access_role IN ('operator', 'admin', 'developer'));
