-- Câmpuri extragere noi pentru 3 tipuri de documente
-- ID 5: Formular de Inregistrare a Vehiculelor (Anexa) -> Licence Plates List
-- ID 8: Proces verbal CargoBox -> Licence Plates List
-- ID 2: Act de identitate -> Serie numar (adaugat la campurile existente)

UPDATE document_types
SET
  extract_fields = '[
    {"name": "Licence Plates List", "type": "text", "description": "Lista tuturor numerelor de inmatriculare (LPN) prezente pe document, concatenate cu virgula si spatiu. Ex: B 123 ABC, TM 45 DEF. Daca nu exista niciun LPN, returneaza null."}
  ]'::jsonb,
  extract_prompt = 'Esti un asistent care extrage date dintr-un FORMULAR DE INREGISTRARE A VEHICULELOR (Anexa) - document intern CargoTrack. Documentul poate contine unul sau mai multe numere de inmatriculare (LPN) inscrise in tabel sau lista.

Reguli per camp:
- "Licence Plates List": toate numerele de inmatriculare gasite pe document, concatenate cu virgula si spatiu (ex: "B 123 ABC, TM 45 DEF"). Cauta in coloane/celule de tip "Nr. inmatriculare", "Numar inmatriculare", "Plate", "LPN" sau similar. Daca nu gasesti niciunul, returneaza null.

Pune null pentru orice valoare care lipseste. Nu inventa.',
  updated_at = now()
WHERE id = 5 AND category = 'vehicul' AND name = 'Formular de Inregistrare a Vehiculelor (Anexa)';

UPDATE document_types
SET
  extract_fields = '[
    {"name": "Licence Plates List", "type": "text", "description": "Lista tuturor numerelor de inmatriculare (LPN) prezente pe procesul verbal, concatenate cu virgula si spatiu. Ex: B 123 ABC, TM 45 DEF. Daca nu exista niciun LPN, returneaza null."}
  ]'::jsonb,
  extract_prompt = 'Esti un asistent care extrage date dintr-un PROCES VERBAL CARGOBOX - document intern de instalare/predare echipament CargoBox. Documentul poate contine unul sau mai multe numere de inmatriculare (LPN) ale vehiculelor pe care s-a instalat echipamentul.

Reguli per camp:
- "Licence Plates List": toate numerele de inmatriculare gasite pe document, concatenate cu virgula si spatiu (ex: "B 123 ABC, TM 45 DEF"). Cauta in campuri de tip "Nr. inmatriculare", "Numar inmatriculare", "Vehicul", "Plate" sau similar. Daca nu gasesti niciunul, returneaza null.

Pune null pentru orice valoare care lipseste. Nu inventa.',
  updated_at = now()
WHERE id = 8 AND category = 'vehicul' AND name = 'Proces verbal CargoBox';

UPDATE document_types
SET
  extract_fields = '[
    {"name": "CNP", "type": "text", "description": "Codul Numeric Personal (CNP), 13 cifre, de pe buletin / carte de identitate. Returneaza doar cifrele."},
    {"name": "Nume si prenume", "type": "text", "description": "Numele si prenumele titularului (campurile Nume si Prenume), combinate intr-un singur sir."},
    {"name": "Adresa de domiciliu", "type": "text", "description": "Adresa completa de domiciliu inscrisa pe document (strada, numar, localitate, judet)."},
    {"name": "Locul nasterii", "type": "text", "description": "Locul nasterii (localitate / judet) inscris pe document."},
    {"name": "Serie numar", "type": "text", "description": "Seria si numarul cartii de identitate concatenate fara spatiu. Ex: XD039263 (seria XD + numarul 039263). Returneaza exact concatenarea serie+numar, fara spatii sau separatori."}
  ]'::jsonb,
  extract_prompt = 'Esti un asistent care extrage date dintr-un ACT DE IDENTITATE romanesc (buletin / carte de identitate), primit ca text (OCR de pe poza). Textul poate fi zgomotos din cauza OCR (diacritice gresite, cifre confundate) - interpreteaza cu bun simt.

Reguli per camp:
- "CNP": Codul Numeric Personal, exact 13 cifre, de obicei langa eticheta "CNP". Returneaza doar cifrele, fara spatii.
- "Nume si prenume": numele si prenumele titularului (campurile "Nume" / "Prenume"). Combina-le intr-un singur sir.
- "Adresa de domiciliu": adresa completa de domiciliu de pe document (dupa "Domiciliu" / "Adresa").
- "Locul nasterii": locul nasterii (localitate / judet), dupa "Loc nastere" / "Nascut(a) in".
- "Serie numar": seria si numarul CI concatenate fara spatiu (ex: "XD039263"). Seria sunt 2 litere, numarul sunt 6 cifre. Cauta langa etichete "Seria", "Nr.", "Serie si numar", "C.I." sau similar. Concateneaza direct, fara spatii sau cratime.

Pune null pentru orice valoare care lipseste. Nu inventa.',
  updated_at = now()
WHERE id = 2 AND category = 'sofer' AND name = 'Act de identitate';
