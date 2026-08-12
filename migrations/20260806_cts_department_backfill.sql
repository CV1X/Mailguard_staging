-- Backfill cts_ground_truth.cts_department din raw->assignment->department_slug.
--
-- CONTEXT: monitorul de productivitate atribuie mailurile pe departamentul TICHETULUI
-- (cts_department), nu pe cel al persoanei asignate — altfel tichetele neasignate dispar.
-- Pe tichetele mai noi, CTS nu mai trimite `department` top-level, doar
-- `assignment.department_slug` cu cratime ("suport-2", "recuperare-tva"). Sync-ul nu normaliza
-- cratima, deci `cts_department` ramanea NULL pe 23 din 243 de tichete DESCHISE — invizibile in
-- monitor. Fix in cod: app/services/cts_groundtruth_sync.py (_map_department + dep_raw fallback).
-- Migratia asta repara rândurile deja scrise.
--
-- Idempotenta: atinge DOAR rândurile cu cts_department IS NULL. Re-rularea nu schimba nimic.
-- Aditiv: nici o operatie structurala, nici o stergere.

BEGIN;

UPDATE cts_ground_truth g
   SET cts_department = m.slug
  FROM (
      SELECT id,
             CASE replace(replace(lower(trim(
                      COALESCE(raw->'assignment'->>'department_slug',
                               raw->'assignment'->>'department_label',
                               raw->>'department'))), '-', '_'), ' ', '_')
                  WHEN 'suport_1'           THEN 'suport_1'
                  WHEN 'suport_2'           THEN 'suport_2'
                  WHEN 'suport_3'           THEN 'suport_3'
                  WHEN 'taxe_de_drum'       THEN 'taxe_drum'
                  WHEN 'taxe_drum'          THEN 'taxe_drum'
                  WHEN 'contabilitate'      THEN 'contabilitate'
                  WHEN 'mobilitate'         THEN 'mobilitate'
                  WHEN 'recuperare_tva'     THEN 'recuperare_tva'
                  WHEN 'comercial'          THEN 'comercial'
                  WHEN 'instalari'          THEN 'instalari'
                  WHEN 'marketing'          THEN 'marketing'
                  WHEN 'administrativ'      THEN 'administrativ'
                  WHEN 'hr'                 THEN 'hr'
                  WHEN 'management_general'  THEN 'management_general'
                  WHEN 'management_operational' THEN 'management_operational'
                  WHEN 'operational'        THEN 'management_operational'
                  WHEN 'account_management' THEN 'account_management'
                  WHEN 'product_management' THEN 'product_management'
                  WHEN 'it'                 THEN 'it'
                  WHEN 'it_team_1'          THEN 'it'
                  WHEN 'it_team'            THEN 'it'
             END AS slug
        FROM cts_ground_truth
       WHERE cts_department IS NULL
  ) m
 WHERE m.id = g.id
   AND m.slug IS NOT NULL
   AND g.cts_department IS NULL;

COMMIT;
