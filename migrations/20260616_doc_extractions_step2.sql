\set ON_ERROR_STOP on
BEGIN;
-- coloane aditive pe document_extractions (Regula 14, DB propriu, idempotent)
ALTER TABLE document_extractions ADD COLUMN IF NOT EXISTS reviewed boolean NOT NULL DEFAULT false;
ALTER TABLE document_extractions ADD COLUMN IF NOT EXISTS updated_at timestamptz DEFAULT now();
ALTER TABLE document_extractions ADD COLUMN IF NOT EXISTS reviewed_by varchar(100);
ALTER TABLE document_extractions ADD COLUMN IF NOT EXISTS manual_type boolean NOT NULL DEFAULT false;
ALTER TABLE document_extractions ADD COLUMN IF NOT EXISTS confidence_reason text;

-- prompt de clasificare editabil din Setari (seed, nu suprascrie daca exista deja)
INSERT INTO settings (key, value, description)
VALUES (
 'documents.classify_prompt',
 to_jsonb($cp$Esti un clasificator de atasamente de email pentru o firma de transport (Cargo Track). Pentru fiecare atasament primesti textul extras din el (PDF sau OCR). Decizi:

1. Daca atasamentul este un DOCUMENT real procesabil (ex: talon / certificat de inmatriculare, carte de identitate a vehiculului CIV, autorizatie CEMT, buletin / pasaport / permis sofer, contract de servicii) SAU este altceva ce NU trebuie procesat: logo, semnatura de email, iconita, banner, antet, screenshot / captura de ecran, imagine decorativa, poza fara continut de document. Pentru acestea din urma pune is_document=false (NEIDENTIFICAT).

2. Daca este document: incadreaza-l intr-o CATEGORIE (vehicul / sofer / contract) si apoi in TIPUL exact din catalogul primit, folosind mai ales TITLUL / headerul documentului si cuvintele-cheie de potrivire. ATENTIE: contractele au structura aproape identica si se deosebesc intre ele aproape exclusiv dupa TITLU.

3. confidence intre 0 si 1, cat de sigur esti de tip. Daca textul e prea putin sau ambiguu, pune confidence mic si type_id null.

Nu inventa un tip care nu e in catalog. Daca e clar un document dar nu se potriveste niciun tip din catalog, pune category (daca o poti deduce) si type_id null.$cp$::text),
 'Prompt de identificare/clasificare a atasamentelor (categorie + tip). Catalogul tipurilor si formatul JSON sunt adaugate automat la rulare.'
)
ON CONFLICT (key) DO NOTHING;
COMMIT;
SELECT column_name FROM information_schema.columns WHERE table_name='document_extractions' ORDER BY ordinal_position;
SELECT key, left(value::text, 60) AS val_head FROM settings WHERE key='documents.classify_prompt';
