# CTS — Mapare tipuri documente și exemple răspuns

**Document de referință pentru integrarea CTS cu endpoint-ul `GET /cts/get_email_documents`.**

Fiecare tip de document are un `document_type_id` fix și un set de câmpuri specific în obiectul `data`.
Câmpurile cu valoarea `null` nu au putut fi extrase sau nu sunt prezente pe document.

> **Notă:** `data` poate fi `{}` (obiect gol) pentru tipuri fără câmpuri de extracție definite.

---

## Categorii

- [vehicul](#categorie-vehicul) — 8 tipuri (id: 1, 3, 4, 5, 6, 7, 8, 37)
- [sofer](#categorie-sofer) — 4 tipuri (id: 2, 20, 21, 36)
- [contract](#categorie-contract) — 22 tipuri (id: 9–19, 22–31, 35)

---

## Categorie: `vehicul`

---

### ID 1 — Certificat de înmatriculare (Talon) 🇷🇴

**Câmpuri extrase:**

| Câmp | Tip | Descriere |
|------|-----|-----------|
| `Licence Plate (A.)` | string | Număr de înmatriculare |
| `First Registration Date (B.)` | date (YYYY-MM-DD) | Data primei înmatriculări |
| `Manufacturer name (D.1.)` | string | Marca / producător |
| `Vin (E.)` | string | Serie șasiu (VIN), 17 caractere |
| `Laden Weight (F.1.)` | number | Masa maximă autorizată (kg) |
| `Engine Capacity (P.1.)` | number | Capacitate cilindrică (cmc) |
| `Fuel Type (P.3.)` | string | Tip combustibil |
| `Unladen Weight (G)` | number | Masa proprie (kg) |
| `Category (J)` | string | Categoria vehiculului (ex: N3, AUTOUTILITARA N3) |
| `Country ()` | string | Cod țară înmatriculare (ex: RO) |
| `Power (P.2)` | number | Putere motor (kW) |

**Exemplu `data`:**
```json
{
  "Licence Plate (A.)": "TM-99-EKO",
  "First Registration Date (B.)": "2022-06-15",
  "Manufacturer name (D.1.)": "DAF",
  "Vin (E.)": "XLRTEF5100G403349",
  "Laden Weight (F.1.)": 19000,
  "Engine Capacity (P.1.)": 10837,
  "Fuel Type (P.3.)": "MOTORINA",
  "Unladen Weight (G)": 8043,
  "Category (J)": "AUTOUTILITARA N3",
  "Country ()": "RO",
  "Power (P.2)": 330
}
```

---

### ID 3 — Carte de Identitate Vehicul (CIV)

**Câmpuri extrase:**

| Câmp | Tip | Descriere |
|------|-----|-----------|
| `Manufacturer name (D.1.)` | string | Marca / producător |
| `Vehicle Type (D.2.)` | string | Tip vehicul |
| `Vehicle model / Commercial name (D.3.)` | string | Model / denumire comercială |
| `Vin (E.)` | string | Serie șasiu (VIN) |
| `Unladen Weight (G.)` | number | Masa proprie (kg) |
| `Category (J.)` | string | Categoria vehiculului |
| `Tractor Axles (L.)` | number | Număr de axe |
| `Engine Capacity (P.1.)` | number | Capacitate cilindrică (cmc) |
| `Fuel Type (P.3.)` | string | Tip combustibil |
| `Emission Class (V.9.)` | string | Clasa de poluare (ex: Euro 6) |
| `Vehicle Model Year (2.)` | number | Anul de fabricație |
| `Laden Weight (F.1)` | number | Masa maximă autorizată (kg) |
| `Gross Weight (7.)` | number | Masa maximă a ansamblului (kg) |
| `Length (10.)` | number | Lungime (mm) |
| `Width (11.)` | number | Lățime (mm) |
| `Height (12.)` | number | Înălțime (mm) |

**Exemplu `data`:**
```json
{
  "Manufacturer name (D.1.)": "DAF",
  "Vehicle Type (D.2.)": "XF",
  "Vehicle model / Commercial name (D.3.)": "XF 480",
  "Vin (E.)": "XLRTEF5100G403349",
  "Unladen Weight (G.)": 8043,
  "Category (J.)": "N3",
  "Tractor Axles (L.)": 2,
  "Engine Capacity (P.1.)": 10837,
  "Fuel Type (P.3.)": "Diesel",
  "Emission Class (V.9.)": "Euro 6",
  "Vehicle Model Year (2.)": 2022,
  "Laden Weight (F.1)": 19000,
  "Gross Weight (7.)": 44000,
  "Length (10.)": 6000,
  "Width (11.)": 2490,
  "Height (12.)": 3800
}
```

---

### ID 4 — Autorizația CEMT

**Câmpuri extrase:**

| Câmp | Tip | Descriere |
|------|-----|-----------|
| `Vin` | string | Serie șasiu (VIN) a vehiculului |
| `Emission Class` | string | Clasa de poluare bifată (EURO III / IV / EEV / V / VI) |

**Exemplu `data`:**
```json
{
  "Vin": "XLRTEF5100G403349",
  "Emission Class": "EURO VI"
}
```

---

### ID 5 — Formular de Înregistrare a Vehiculelor (Anexa)

Fără câmpuri de extracție definite — document de tip formular completat manual.

**Exemplu `data`:**
```json
{}
```

---

### ID 6 — Documente Remorcă

Fără câmpuri de extracție definite — document compozit (poate conține talon remorcă, ITP etc.).

**Exemplu `data`:**
```json
{}
```

---

### ID 7 — Certificat de înmatriculare MD (Talon) 🇲🇩

**Câmpuri extrase:**

| Câmp | Tip | Descriere |
|------|-----|-----------|
| `Licence Plate (A.)` | string | Număr de înmatriculare |
| `Vehicle Model Year (B.)` | number | Anul primei înmatriculări |
| `Manufacturer name (D.1.)` | string | Marca / producător |
| `Commercial Name (D.3.)` | string | Denumire comercială / model |
| `Vin (E.)` | string | Serie șasiu (VIN) |
| `Laden Weight (F.1.)` | number | Masa maximă autorizată (kg) |
| `Unladen Weight (G.)` | number | Masa proprie (kg) |
| `Category (J.)` | string | Categoria vehiculului |
| `Engine Capacity (P.1.)` | number | Capacitate cilindrică (cmc) |
| `Fuel Type (P.3.)` | string | Tip combustibil |
| `Country ()` | string | Cod țară (MD) |

**Exemplu `data`:**
```json
{
  "Licence Plate (A.)": "C 123 ABC",
  "Vehicle Model Year (B.)": 2018,
  "Manufacturer name (D.1.)": "VOLVO",
  "Commercial Name (D.3.)": "FH 500",
  "Vin (E.)": "YV2RT40A6KB123456",
  "Laden Weight (F.1.)": 18000,
  "Unladen Weight (G.)": 7500,
  "Category (J.)": "N3",
  "Engine Capacity (P.1.)": 12777,
  "Fuel Type (P.3.)": "MOTORINA",
  "Country ()": "MD"
}
```

---

### ID 8 — Proces Verbal CargoBox

Fără câmpuri de extracție definite — document intern de instalare/predare echipament.

**Exemplu `data`:**
```json
{}
```

---

### ID 37 — Certificat de Conformitate (COC)

**Câmpuri extrase:**

| Câmp | Tip | Descriere |
|------|-----|-----------|
| `Vin (E.)` | string | Serie șasiu VIN (17 caractere alfanumerice) |
| `CO2 Emission (V.7.)` | number | Emisii CO2 combinate (g/km, WLTP sau NEDC) |
| `Power (P.2.)` | number | Putere maximă netă (kW) |
| `Vehicle Group ()` | string\|null | Grupa vehiculului (clasificare emisii). `null` dacă lipsește. |
| `Vehicle Subgroup ()` | string\|null | Subgrupa vehiculului. `null` dacă lipsește. |

**Exemplu `data`:**
```json
{
  "Vin (E.)": "XLRTEF5100G403349",
  "CO2 Emission (V.7.)": 195,
  "Power (P.2.)": 330,
  "Vehicle Group ()": null,
  "Vehicle Subgroup ()": null
}
```

---

## Categorie: `sofer`

---

### ID 2 — Act de Identitate

**Câmpuri extrase:**

| Câmp | Tip | Descriere |
|------|-----|-----------|
| `CNP` | string | Codul Numeric Personal, 13 cifre |
| `Nume si prenume` | string | Numele și prenumele titularului |
| `Adresa de domiciliu` | string | Adresa completă de domiciliu |
| `Locul nasterii` | string | Localitate și județ |

**Exemplu `data`:**
```json
{
  "CNP": "1850315123456",
  "Nume si prenume": "POPESCU ION",
  "Adresa de domiciliu": "Str. Florilor nr. 5, Timișoara, Timiș",
  "Locul nasterii": "Timișoara, Timiș"
}
```

---

### ID 20 — Permis de Conducere

**Câmpuri extrase:**

| Câmp | Tip | Descriere |
|------|-----|-----------|
| `Seria permis` | string | Seria și numărul permisului de conducere (câmpul 5) |

**Exemplu `data`:**
```json
{
  "Seria permis": "TM123456"
}
```

---

### ID 21 — Reprezentare (Sofer)

Fără câmpuri de extracție definite — document de împuternicire/procură.

**Exemplu `data`:**
```json
{}
```

---

### ID 36 — Contract Individual de Muncă

**Câmpuri extrase:**

| Câmp | Tip | Descriere |
|------|-----|-----------|
| `Data inceperii activitatii` | date (YYYY-MM-DD) | Data începerii activității din CIM, punctul C |

**Exemplu `data`:**
```json
{
  "Data inceperii activitatii": "2024-03-01"
}
```

---

## Categorie: `contract`

### Câmpuri standard pentru contracte (22 din 22 tipuri)

Marea majoritate a tipurilor de contract extrag aceleași 6 câmpuri:

| Câmp | Tip | Descriere |
|------|-----|-----------|
| `Numar contract` | string | Numărul contractului din antet (ex: `1874867`) |
| `Data contract` | date (YYYY-MM-DD) | Data semnării contractului |
| `Prestator` | string | Firma prestatoare (de regulă Cargo Track Solutions SRL sau Cargo Track Telematics SRL) |
| `Client` | string | Denumirea firmei beneficiare/client (NU Cargo Track) |
| `CUI client` | string | Codul fiscal/CUI al clientului (ex: `RO21317878`) |
| `Este semnat` | boolean | `true` dacă există dovadă textuală a semnăturii clientului |

**Exemplu `data` standard:**
```json
{
  "Numar contract": "1874867",
  "Data contract": "2026-04-24",
  "Prestator": "CARGO TRACK SOLUTIONS SRL",
  "Client": "TRANSPORT XYZ SRL",
  "CUI client": "RO21317878",
  "Este semnat": true
}
```

**Tipuri cu câmpuri standard** (toate id-urile de mai jos au același format `data`):

| ID | Nume tip |
|----|----------|
| 9 | CargoFuel Prepaid v1.0 |
| 10 | E-Transport Premium |
| 11 | E-Transport Basic |
| 12 | Serviciu SentGeo - Polonia |
| 13 | HUGO - Basic |
| 14 | Monitorizare GPS |
| 15 | Taxe de drum Polonia |
| 16 | Taxe de drum Ungaria |
| 17 | Taxe de drum Bulgaria |
| 19 | Compensare carburant |
| 22 | CargoFuel Postpaid v1.0 |
| 23 | Certificate si Reprezentare - FULL EU - Drivers |
| 24 | Formular A1 (Contract de prestari servicii) |
| 25 | Intocmire dosar privind acordarea ajutorului de stat pentru compensarea pretului la combustibil 2024 |
| 26 | Contract de comodat + Optiune Extra SEE FULL |
| 27 | Recuperare TVA |
| 28 | HUGO - Premium |
| 29 | Recuperare TVA cu plata rapida |
| 30 | Reprezentare IMI \| 1 - 5 tari \| Soferi |
| 31 | Reprezentare IMI \| Full EU \| Soferi |
| 35 | TachoTrack - Analiza tahograf |

---

### ID 18 — Taxe de drum "carGObox - PrePaid" ⚠ câmpuri extinse

Acest tip are câmpuri suplimentare față de contractul standard (date fidejusor):

| Câmp | Tip | Descriere |
|------|-----|-----------|
| `Numar contract` | string | Numărul contractului |
| `Data contract` | date (YYYY-MM-DD) | Data contractului |
| `Prestator` | string | Firma prestatoare |
| `Client` | string | Denumirea firmei beneficiare |
| `CUI client` | string\|null | CUI beneficiar |
| `Fidejusor nume` | string\|null | Numele complet al fidejusorului (adesea scris de mână) |
| `Fidejusor C.I.` | string\|null | Seria și numărul cărții de identitate a fidejusorului |
| `Fidejusor CNP` | string\|null | CNP fidejusor (13 cifre); `null` dacă nu e lizibil |
| `Semnatura beneficiar` | boolean | `true` dacă beneficiarul a semnat |
| `Semnatura fidejusor` | boolean | `true` dacă fidejusorul a semnat |

**Exemplu `data`:**
```json
{
  "Numar contract": "1874867",
  "Data contract": "2026-04-24",
  "Prestator": "CARGO TRACK SOLUTIONS SRL",
  "Client": "TRANSPORT XYZ SRL",
  "CUI client": "RO21317878",
  "Fidejusor nume": "IONESCU GHEORGHE",
  "Fidejusor C.I.": "TM 123456",
  "Fidejusor CNP": "1780512123456",
  "Semnatura beneficiar": true,
  "Semnatura fidejusor": true
}
```

---

## Rezumat rapid — ID → tip → câmpuri cheie

| ID | Categorie | Tip | Câmp cheie de identificare |
|----|-----------|-----|---------------------------|
| 1 | vehicul | Talon RO | `Licence Plate (A.)`, `Vin (E.)` |
| 2 | sofer | Act de identitate | `CNP`, `Nume si prenume` |
| 3 | vehicul | CIV | `Vin (E.)`, `Manufacturer name (D.1.)` |
| 4 | vehicul | Autorizație CEMT | `Vin`, `Emission Class` |
| 5 | vehicul | Formular Înregistrare (Anexa) | — (fără câmpuri) |
| 6 | vehicul | Documente remorcă | — (fără câmpuri) |
| 7 | vehicul | Talon MD | `Licence Plate (A.)`, `Vin (E.)` |
| 8 | vehicul | Proces verbal CargoBox | — (fără câmpuri) |
| 9–19, 22–31, 35 | contract | (standard) | `Numar contract`, `Client`, `CUI client` |
| 18 | contract | carGObox PrePaid | `Numar contract`, `Fidejusor CNP` |
| 20 | sofer | Permis de conducere | `Seria permis` |
| 21 | sofer | Reprezentare | — (fără câmpuri) |
| 36 | sofer | Contract individual de muncă | `Data inceperii activitatii` |
| 37 | vehicul | COC | `Vin (E.)`, `CO2 Emission (V.7.)` |
