-- Config motor satisfacție v4 (per lună calendaristică).
-- Seed idempotent al ponderilor/penalităților în tabela settings, key 'satisfaction.v4'.
-- Motorul (app/services/satisfaction_engine.py::_load_v4_config) citește această cheie;
-- dacă lipsește, cade pe defaults hardcodate identice cu cele de mai jos.
--
-- pen_sesizare   : penalizare per mail/apel de tip 'sesizare' (KPI Emoție)
-- pen_reclamatie : penalizare per mail/apel de tip 'reclamatie'
-- pen_recontact  : penalizare per revenire explicită pe problemă nerezolvată (marcată de IRIS)
-- w_emotion      : pondere KPI Emoție în scorul final (0.70)
-- w_context      : pondere KPI Context IRIS în scorul final (0.30)
-- recovery_max   : fracția maximă din penalizări pe care IRIS o poate restitui (0.50)

INSERT INTO settings (key, value, description, updated_by, updated_at)
VALUES (
    'satisfaction.v4',
    '{"pen_sesizare": 10, "pen_reclamatie": 20, "pen_recontact": 5, "w_emotion": 0.70, "w_context": 0.30, "recovery_max": 0.50}'::jsonb,
    'Config motor satisfacție v4: penalizări pe categorie + reveniri, ponderi Emoție/Context, plafon restituire.',
    'migration_20260724_satisfaction_v4_config',
    NOW()
)
ON CONFLICT (key) DO NOTHING;
