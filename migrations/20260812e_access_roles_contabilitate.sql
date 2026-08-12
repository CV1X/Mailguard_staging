-- v2.6.1 — Completare seed roluri: departamentul contabilitate -> operator.
--
-- De ce fisier separat: 20260812d a fost deja marcat aplicat pe staging, iar
-- scripts/migrate.sh sare peste fisierele din _release_migrations. Cei 6 oameni
-- de mai jos au fost atribuiti din interfata DUPA acea migratie, deci fara acest
-- fisier ar exista pe staging dar NU pe productie.
--
-- Idempotent: ON CONFLICT DO NOTHING — nu suprascrie o decizie luata ulterior
-- din interfata (ex. daca cineva din contabilitate e promovat admin intre timp).

INSERT INTO access_role_assignments (email, access_role, assigned_by, note) VALUES
    -- IT: Tudor Huza lucreaza pe aplicatie, dar nu e in employee_department_mapping
    -- (nu e adus in aplicatie din CTS). Setat developer de Raul din interfata pe
    -- staging; fara randul asta ar ajunge 'operator' pe productie.
    ('tudor.huza@trakosoft.ro',        'developer', 'seed-v2.6.1', 'IT'),
    ('adelina.pop@cargotrack.ro',      'operator', 'seed-v2.6.1', 'contabilitate'),
    ('madalina.apetrei@cargotrack.ro', 'operator', 'seed-v2.6.1', 'contabilitate'),
    ('maria.tomuta@cargotrack.ro',     'operator', 'seed-v2.6.1', 'contabilitate'),
    ('oana.lasca@cargotrack.ro',       'operator', 'seed-v2.6.1', 'contabilitate'),
    ('raluca.dogar@cargotrack.ro',     'operator', 'seed-v2.6.1', 'contabilitate'),
    ('romina.ivan@cargotrack.ro',      'operator', 'seed-v2.6.1', 'contabilitate')
ON CONFLICT (email) DO NOTHING;

-- Aplica pe conturile care exista deja (nu creeaza conturi).
UPDATE admin_users a
   SET access_role = r.access_role
  FROM access_role_assignments r
 WHERE lower(a.email) = lower(r.email)
   AND a.access_role <> r.access_role;
