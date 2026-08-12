-- Tipuri de documente noi pentru contractele carGObox / ETOLL (cerere UX 2026-07-30).
-- Se adaugă DOAR tipurile (fără șablon încărcat) — șabloanele se urcă manual din UI,
-- la „Tipuri de documente" → Șablon. De aceea sample_path/sample_name rămân NULL.
--
-- „Act de identitate" (buletin/pașaport) EXISTĂ deja (id 2, categoria sofer) și NU se atinge.
--
-- Idempotent: ON CONFLICT țintește indexul unic PARȚIAL existent
--   uq_document_types_cat_name ON (category, lower(name)) WHERE status='active'
-- (verificat pe staging: e index unic parțial, NU un constraint — de aceea inferența de
-- conflict trebuie scrisă exact așa, cu lower(name) și cu predicatul WHERE).
-- Aditiv: nu modifică și nu șterge tipuri existente.

-- Gardă: dacă indexul lipsește (bază nouă), îl creăm identic înainte de insert.
CREATE UNIQUE INDEX IF NOT EXISTS uq_document_types_cat_name
    ON document_types (category, lower(name)) WHERE status = 'active';

INSERT INTO document_types (category, name, description, created_by, enabled, status)
VALUES
    -- CUI = certificat de înmatriculare al FIRMEI (nu al vehiculului) => categoria 'contract',
    -- fiind cerut la dosarul de contract. Categoriile permise sunt doar vehicul|sofer|contract.
    ('contract',
     'CUI / Extras pe contract carGObox sau ETOLL',
     'Certificat de înmatriculare al firmei (CUI) sau extras de la Registrul Comerțului, '
     'necesar la dosarul de contract carGObox sau ETOLL. Șablon de încărcat.',
     'iris-ux-20260730', TRUE, 'active'),
    ('contract',
     'Anexa 2 - contract carGObox',
     'Anexa 2 la contractul carGObox (tip de contract). Șablon de încărcat.',
     'iris-ux-20260730', TRUE, 'active'),
    ('contract',
     'Anexa 3 - contract carGObox',
     'Anexa 3 la contractul carGObox (tip de contract). Șablon de încărcat.',
     'iris-ux-20260730', TRUE, 'active'),
    ('contract',
     'Anexa 4 - contract carGObox',
     'Anexa 4 la contractul carGObox (tip de contract). Șablon de încărcat.',
     'iris-ux-20260730', TRUE, 'active')
ON CONFLICT (category, lower(name)) WHERE status = 'active' DO NOTHING;
