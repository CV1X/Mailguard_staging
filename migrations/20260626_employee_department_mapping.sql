-- 2026-06-26: employee_department_mapping — tabel ORFAN (creat ad-hoc pe staging, fara migratie).
-- Codul (settings.py /settings/employees, department_classifier employee signature match) il foloseste,
-- dar nu exista nicio migratie care sa-l creeze => lipseste pe productie => 500 dupa release.
-- Aceasta migratie il creeaza + seed angajati. Idempotenta (IF NOT EXISTS + ON CONFLICT DO NOTHING).

CREATE TABLE IF NOT EXISTS employee_department_mapping (
    id          integer NOT NULL,
    name        text NOT NULL,
    department  text NOT NULL,
    enabled     boolean NOT NULL DEFAULT true,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    created_by  text NOT NULL DEFAULT 'admin'
);

CREATE SEQUENCE IF NOT EXISTS employee_department_mapping_id_seq
    AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
ALTER SEQUENCE employee_department_mapping_id_seq OWNED BY employee_department_mapping.id;
ALTER TABLE employee_department_mapping ALTER COLUMN id SET DEFAULT nextval('employee_department_mapping_id_seq'::regclass);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'employee_department_mapping_pkey') THEN
    ALTER TABLE employee_department_mapping ADD CONSTRAINT employee_department_mapping_pkey PRIMARY KEY (id);
  END IF;
END $$;

-- Seed angajati CargoTrack (sincron cu staging la 2026-06-26). Nu suprascrie randuri existente.
INSERT INTO employee_department_mapping (id, name, department, enabled) VALUES
(1,'Ambrus Anamaria','recuperare_tva',true),
(2,'Berde Claudia-Nicoleta','recuperare_tva',true),
(3,'Corciu Evelina','recuperare_tva',true),
(4,'Potre Cristina Florina','recuperare_tva',true),
(5,'Apetrei Ioana Madalina','contabilitate',true),
(6,'Dogar Raluca-Mirela','contabilitate',true),
(7,'Ivan Romina-Claudia','contabilitate',true),
(8,'Lasca Oana-Maria','contabilitate',true),
(9,'Pop Adelina Felicia','contabilitate',true),
(10,'Tomuta Maria','contabilitate',true),
(11,'Bogdan Cosmin Florin','mobilitate',true),
(12,'Boros Vanessa-Karolina','suport_1',true),
(13,'Breahna Andrei','suport_1',true),
(14,'Buda Alina-Mioara','suport_1',true),
(15,'Judea Bianca-Denisa','suport_1',true),
(16,'Negrescu Elena','suport_1',true),
(17,'Olar Andrei-Bogdan','suport_1',true),
(18,'Bursasiu Ionut-Mihai','comercial',true),
(19,'Chirita Anastasia','comercial',true),
(20,'Ciuraru Claudiu-Stefan','comercial',true),
(21,'Cotelea Nicolae','comercial',true),
(22,'Groza Tudor Nicolae','comercial',true),
(23,'Popa Andreea Monica','comercial',true),
(24,'Roman Sergiu','comercial',true),
(25,'Buse Angelica-Adriana','taxe_drum',true),
(26,'Pusta Vlad Ionut','taxe_drum',true),
(27,'Cuc Mihai','suport_2',true),
(28,'Iova Oliviu-Robert','suport_2',true),
(29,'Kovacs Robert','suport_2',true),
(30,'Miclau Adrian-David','suport_2',true),
(31,'Ticus Ovidiu Alexandru','suport_2',true),
(32,'Tyepak Zoltan','suport_3',true)
ON CONFLICT (id) DO NOTHING;

-- Aliniaza secventa dupa seed (no-op daca tabelul avea deja date)
SELECT setval('employee_department_mapping_id_seq', (SELECT GREATEST(MAX(id), 1) FROM employee_department_mapping));
