-- Sincronizare reguli departament staging → prod.
-- Merge idempotent: adaugă regulile noi din staging care lipsesc pe prod (după id).
-- Nu suprascrie regulile existente pe prod (editate manual acolo).
-- Rulat automat la Release via scripts/migrate.sh.

DO $$
DECLARE
    staging_rules jsonb := '[
        {"at":"2026-06-18T09:05:11.993071+00:00","by":"seed","id":"37382654","from":"support@locatorbg.com","note":"locatorbg + refund -> taxe","enabled":true,"subject":"Request for refund -","department":"taxe_drum"},
        {"at":"2026-06-18T09:05:11.993111+00:00","by":"seed","id":"f5b800ac","from":"no-reply@idata.hu","note":"idata.hu utilizare neautorizata -> taxe","enabled":true,"subject":"Presumed unauthorized road use","department":"taxe_drum"},
        {"at":"2026-06-18T09:05:11.993154+00:00","by":"seed","id":"75feabc6","from":"alert@ct.its-pro.hu","note":"ITS-Pro Hungary alert -> taxe","enabled":true,"subject":"","department":"taxe_drum"},
        {"at":"2026-06-18T09:05:11.993192+00:00","by":"seed","id":"0f22de9d","from":"noreply@nemzetiutdij.hu","note":"Nemzeti Utdij Hungary -> taxe","enabled":true,"subject":"","department":"taxe_drum"},
        {"at":"2026-06-18T09:05:11.993230+00:00","by":"seed","id":"3a7851f6","from":"noreply@hu-go.hu","note":"HU-GO Hungary -> taxe","enabled":true,"subject":"","department":"taxe_drum"},
        {"at":"2026-06-18T09:05:11.993267+00:00","by":"seed","id":"bb216f7f","from":"support@locatorbg.com","note":"locatorbg purchase receipt -> contabilitate","enabled":true,"subject":"Your Purchase Receipt from DigiToll","department":"contabilitate"},
        {"at":"2026-06-18T09:05:11.993303+00:00","by":"seed","id":"a9d1b74c","from":"urbansiasociatii.ro","note":"Urban si Asociatii -> contabilitate","enabled":true,"subject":"","department":"contabilitate"},
        {"at":"2026-06-18T09:05:11.993340+00:00","by":"seed","id":"480491f6","from":"mis.batch@btrl.ro","note":"BTRL extras zilnic -> contabilitate","enabled":true,"subject":"","department":"contabilitate"},
        {"at":"2026-06-18T09:05:11.993377+00:00","by":"seed","id":"ab626f88","from":"","note":"Tranzactii zilnice BRD -> contabilitate","enabled":true,"subject":"Tranzactii zilnice","department":"contabilitate"},
        {"at":"2026-06-18T09:05:11.993414+00:00","by":"seed","id":"ea0c3130","from":"zoli","note":"Zoli intern -> suport_3","enabled":true,"subject":"","department":"suport_3"},
        {"at":"2026-06-18T09:05:11.993451+00:00","by":"seed","id":"233defca","from":"tyepak","note":"Tyepak -> suport_3","enabled":true,"subject":"","department":"suport_3"},
        {"at":"2026-06-18T09:05:11.993488+00:00","by":"seed","id":"54d9492e","from":"cosmin.bogdan@cargotrack.ro","note":"Cosmin intern -> mobilitate","enabled":true,"subject":"","department":"mobilitate"},
        {"at":"2026-06-18T09:05:11.993525+00:00","by":"seed","id":"70a8ea0e","from":"guretruck","note":"Guretruck -> mobilitate","enabled":true,"subject":"","department":"mobilitate"},
        {"at":"2026-06-18T09:05:11.993562+00:00","by":"seed","id":"5a029229","from":"transportinnood","note":"Transport in nood -> mobilitate","enabled":true,"subject":"","department":"mobilitate"},
        {"at":"2026-06-18T09:05:11.993599+00:00","by":"seed","id":"eb122583","from":"","note":"","enabled":true,"subject":"","department":"mobilitate"},
        {"at":"2026-06-20T00:00:00.000000+00:00","by":"seed","id":"sd001","from":"smartdiesel.ro","note":"SmartDiesel facturi -> contabilitate","enabled":true,"subject":"","department":"contabilitate"},
        {"at":"2026-06-20T00:00:00.000000+00:00","by":"seed","id":"exp001","from":"expert-erp.net","note":"Expert ERP -> contabilitate","enabled":true,"subject":"","department":"contabilitate"},
        {"at":"2026-06-24T00:00:00.000000+00:00","by":"cc-agent","id":"eac19387","from":"digitoll.bg","note":"DigiToll Bulgaria purchase receipt -> contabilitate","enabled":true,"subject":"Purchase Receipt","department":"contabilitate"},
        {"at":"2026-06-24T00:00:00.000000+00:00","by":"cc-agent","id":"7be469d1","from":"itsbulgaria.com","note":"ITS Bulgaria raport -> taxe_drum","enabled":true,"subject":"отчет","department":"taxe_drum"},
        {"at":"2026-06-26T09:13:46.772225+00:00","by":"cc-agent:dept-cnpp","id":"56d7d190","from":"portal@cnpp.ro","note":"CNPP portal (documente sofer/pensii) -> mobilitate (5/5 consistent in CTS)","enabled":true,"subject":"","department":"mobilitate"},
        {"at":"2026-07-01T00:00:00.000000+00:00","by":"cc-agent","id":"cgghitech01","from":"factura@cg-hitech.ro","note":"CG Hitech facturi -> contabilitate","enabled":true,"subject":"","department":"contabilitate"},
        {"at":"2026-07-01T00:00:00.000000+00:00","by":"cc-agent","id":"suspend01","from":"","note":"suspendare servicii pentru neplata -> contabilitate","enabled":true,"subject":"suspendare servicii pentru neplat","department":"contabilitate"},
        {"at":"2026-07-10T00:00:00.000000+00:00","by":"cc-agent","id":"tvaext01","from":"","note":"oferta rambursare TVA extern -> recuperare_tva","enabled":true,"subject":"oferta rambursare tva extern","department":"recuperare_tva"},
        {"at":"2026-07-10T00:00:00.000000+00:00","by":"cc-agent","id":"tvaext02","from":"","note":"rambursare TVA extern -> recuperare_tva","enabled":true,"subject":"rambursare tva extern","department":"recuperare_tva"}
    ]'::jsonb;
    current_store jsonb;
    current_rules jsonb;
    existing_ids text[];
    new_rule jsonb;
    merged_rules jsonb;
BEGIN
    -- Citim store-ul curent (sau inițializăm dacă lipsește)
    SELECT value INTO current_store FROM settings WHERE key = 'department_rules';
    IF current_store IS NULL THEN
        current_store := '{"rules": []}'::jsonb;
    END IF;
    current_rules := COALESCE(current_store -> 'rules', '[]'::jsonb);

    -- Colectăm id-urile existente
    SELECT array_agg(r ->> 'id')
    INTO existing_ids
    FROM jsonb_array_elements(current_rules) AS r;

    existing_ids := COALESCE(existing_ids, '{}');

    -- Adăugăm doar regulile lipsă (după id)
    merged_rules := current_rules;
    FOR new_rule IN SELECT * FROM jsonb_array_elements(staging_rules)
    LOOP
        IF NOT (new_rule ->> 'id' = ANY(existing_ids)) THEN
            merged_rules := merged_rules || jsonb_build_array(new_rule);
        END IF;
    END LOOP;

    -- Scriem înapoi
    INSERT INTO settings(key, value)
    VALUES ('department_rules', jsonb_build_object('rules', merged_rules))
    ON CONFLICT (key) DO UPDATE
        SET value = jsonb_build_object('rules', merged_rules);
END $$;
