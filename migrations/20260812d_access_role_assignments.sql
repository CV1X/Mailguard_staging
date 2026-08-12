-- v2.6.0 — Pre-atribuire roluri pe email (inainte ca omul sa aiba cont).
--
-- Problema: access_role traieste pe admin_users, dar conturile se creeaza abia la
-- prima logare prin IRIS SSO. Nu poti seta rolul cuiva care nu s-a logat inca.
--
-- Solutie: tabel de intentii, cheie = email. La provisioning-ul SSO se citeste de
-- aici rolul; daca nu exista intrare -> 'operator' (deny-by-default).
-- Sursa numelor/departamentelor ramine employee_department_mapping (sync CTS).

CREATE TABLE IF NOT EXISTS access_role_assignments (
    email        varchar(320) PRIMARY KEY,
    access_role  varchar(20)  NOT NULL DEFAULT 'operator',
    assigned_by  varchar(100),
    note         text,
    created_at   timestamptz  NOT NULL DEFAULT now(),
    updated_at   timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT access_role_assignments_role_chk
        CHECK (access_role IN ('operator', 'admin', 'developer'))
);

CREATE INDEX IF NOT EXISTS idx_access_role_assignments_role
    ON access_role_assignments (access_role);

-- Seed initial (decis de Raul Covaci, 2026-08-12):
--   suport_1  -> operator, exceptie Bianca Judea (admin)
--   suport_2  -> operator, exceptie Robert Kovacs (admin)
--   taxe_drum -> operator, exceptie Pusta Vlad (admin)
--   Calin Lucaciu (management_operational) -> admin
--   Razvan + Raul -> developer
INSERT INTO access_role_assignments (email, access_role, assigned_by, note) VALUES
    -- developeri
    ('razvan.perticas@cargotrack.ro', 'developer', 'seed-v2.6.0', 'CEO'),
    ('raul.covaci@trakosoft.ro',      'developer', 'seed-v2.6.0', 'IT/Product Owner'),
    -- admini
    ('bianca.judea@cargotrack.ro',    'admin',     'seed-v2.6.0', 'suport_1'),
    ('robert.kovacs@cargotrack.ro',   'admin',     'seed-v2.6.0', 'suport_2'),
    ('vlad.pusta@cargotrack.ro',      'admin',     'seed-v2.6.0', 'taxe_drum'),
    ('calin.lucaciu@cargotrack.ro',   'admin',     'seed-v2.6.0', 'management_operational / COO'),
    -- suport_1 -> operator
    ('vanessa.boros@cargotrack.ro',   'operator',  'seed-v2.6.0', 'suport_1'),
    ('andrei.breahna@cargotrack.ro',  'operator',  'seed-v2.6.0', 'suport_1'),
    ('alina.buda@cargotrack.ro',      'operator',  'seed-v2.6.0', 'suport_1'),
    ('anamaria.bulmau@cargotrack.ro', 'operator',  'seed-v2.6.0', 'suport_1'),
    ('elena.negrescu@cargotrack.ro',  'operator',  'seed-v2.6.0', 'suport_1'),
    ('andrei.olar@cargotrack.ro',     'operator',  'seed-v2.6.0', 'suport_1'),
    -- suport_2 -> operator
    ('crinel.baican@cargotrack.ro',   'operator',  'seed-v2.6.0', 'suport_2'),
    ('mihai.cuc@cargotrack.ro',       'operator',  'seed-v2.6.0', 'suport_2'),
    ('robert.iova@cargotrack.ro',     'operator',  'seed-v2.6.0', 'suport_2'),
    ('david.miclau@cargotrack.ro',    'operator',  'seed-v2.6.0', 'suport_2'),
    ('ovidiu.ticus@cargotrack.ro',    'operator',  'seed-v2.6.0', 'suport_2'),
    -- taxe_drum -> operator
    ('adriana.brasovean@cargotrack.ro','operator', 'seed-v2.6.0', 'taxe_drum'),
    -- contabilitate -> operator
    ('adelina.pop@cargotrack.ro',      'operator', 'seed-v2.6.0', 'contabilitate'),
    ('madalina.apetrei@cargotrack.ro', 'operator', 'seed-v2.6.0', 'contabilitate'),
    ('maria.tomuta@cargotrack.ro',     'operator', 'seed-v2.6.0', 'contabilitate'),
    ('oana.lasca@cargotrack.ro',       'operator', 'seed-v2.6.0', 'contabilitate'),
    ('raluca.dogar@cargotrack.ro',     'operator', 'seed-v2.6.0', 'contabilitate'),
    ('romina.ivan@cargotrack.ro',      'operator', 'seed-v2.6.0', 'contabilitate')
ON CONFLICT (email) DO NOTHING;

-- Aplica intentiile pe conturile care EXISTA deja.
UPDATE admin_users a
   SET access_role = r.access_role
  FROM access_role_assignments r
 WHERE lower(a.email) = lower(r.email)
   AND a.access_role <> r.access_role;
