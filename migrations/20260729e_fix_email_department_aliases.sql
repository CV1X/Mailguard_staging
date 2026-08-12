-- Fix: departamentul emailurilor CTS rămânea nesluggificat pentru departamentele
-- care nu există în DEPT_LABELS.
--
-- Constatare (staging, 2026-07-29): `cts_ground_truth.cts_department` conținea valori brute
-- CTS — `Administrativ` (71), `Operational` (33), `Product Management` (32), `Management General`
-- (16), `Instalari` (13), `IT Team 1` (11), `Marketing` (8), `HR` (8), `IT` (2).
--
-- Cauză: `_map_department()` normalizează pe `DEPARTMENTS` / `DEPT_LABELS` — lista de 8
-- departamente pe care poate alege clasificatorul AI — dar `employee_department_mapping` are 16.
-- Pentru cele 8 lipsă funcția cădea pe fallback (`return str(v), False`), păstrând valoarea brută.
-- Rezultat: volumul lor nu se agrega în nicio raportare pe departament (slug-urile nu se potriveau).
--
-- Codul: aliasurile au fost adăugate în `cts_groundtruth_sync._DEPT_ALIASES` (nu în DEPT_LABELS,
-- ca să nu extindem lista pe care alege AI-ul).
--
-- Idempotent: re-rularea nu mai găsește valorile brute.

UPDATE cts_ground_truth SET cts_department = 'administrativ'          WHERE cts_department = 'Administrativ';
UPDATE cts_ground_truth SET cts_department = 'management_operational' WHERE cts_department = 'Operational';
UPDATE cts_ground_truth SET cts_department = 'product_management'     WHERE cts_department = 'Product Management';
UPDATE cts_ground_truth SET cts_department = 'management_general'     WHERE cts_department = 'Management General';
UPDATE cts_ground_truth SET cts_department = 'instalari'              WHERE cts_department IN ('Instalari', 'Instalări');
UPDATE cts_ground_truth SET cts_department = 'marketing'              WHERE cts_department = 'Marketing';
UPDATE cts_ground_truth SET cts_department = 'hr'                     WHERE cts_department IN ('HR', 'Resurse Umane');
UPDATE cts_ground_truth SET cts_department = 'it'                     WHERE cts_department IN ('IT', 'IT Team 1', 'IT Team');

-- Verificare: orice valoare rămasă care nu e un slug (conține majusculă sau spațiu).
DO $$
DECLARE n INT; v TEXT;
BEGIN
    SELECT count(*), string_agg(DISTINCT cts_department, ', ') INTO n, v
    FROM cts_ground_truth
    WHERE cts_department IS NOT NULL AND (cts_department <> lower(cts_department) OR cts_department LIKE '% %');
    IF n > 0 THEN
        RAISE NOTICE 'ATENTIE: % randuri cu department nesluggificat rămase: %', n, v;
    ELSE
        RAISE NOTICE 'Toate departamentele emailurilor sunt sluggificate.';
    END IF;
END $$;
