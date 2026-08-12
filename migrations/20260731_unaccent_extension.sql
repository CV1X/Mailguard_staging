-- Extensia unaccent — necesara pentru potrivirea numelor insensibila la diacritice.
--
-- Folosita de app/services/device_ops_suport2_sync.py (_resolve_employee_by_name), care inlocuieste
-- whitelist-ul de ID-uri hardcodate cu un lookup pe nume in employee_department_mapping. Fara
-- extensia asta, sincronizarea operatiunilor pe device eseca la prima rulare cu:
--   ERROR: function unaccent(text) does not exist
--
-- Pe staging lipsea complet (doar plpgsql era instalat) — descoperit 2026-07-31.
-- Idempotent. Necesita drepturi de superuser sau rolul pg_database_owner pe baza aplicatiei.

CREATE EXTENSION IF NOT EXISTS unaccent;
