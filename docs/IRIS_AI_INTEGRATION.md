# Cargo360 ↔ IRIS AI — ghid integrare pentru dezvoltator

**Status:** LIVE și testat (2026-06-10). Canalul prin care Cargo360 trimite prompt-uri formatate
către IRIS și primește răspunsuri de la modele Claude. Infrastructura e gata — tu doar adaugi
„consumatori" (taskuri concrete: interpretare intenție mail, summary worklog, clasificări etc.).

---

## 1. Ce există deja

| Component | Rol |
|---|---|
| `app/services/iris_ai.py` | Client generic. Funcția `run_prompt(system, content, ...)`. **Folosește asta pentru taskuri din backend.** |
| `app/api/v1/ai.py` | Endpoint HTTP: `POST /api/v1/ai/run-prompt` + `GET /api/v1/ai/status` (necesită JWT de admin). Pentru apeluri din UI/extern. |
| `app/services/nova_llm.py` | Primul consumator real (summary worklog la fiecare backup). Model de urmat. |

Config în `.env` (deja setat — nu trebuie să atingi):
- `IRIS_API_URL=https://iris.cargotrack.ro` → URL-ul se derivă automat (`/external-ai/run-prompt`)
- `IRIS_AI_KEY=...` → cheia aplicației Cargo360 înregistrată în IRIS (Bearer auth)

Verificare rapidă că e configurat: `GET /api/v1/ai/status` → `{"configured": true, ...}`.

---

## 2. Cum chemi IRIS din backend (recomandat)

```python
from app.services import iris_ai

res = iris_ai.run_prompt(
    system="<instrucțiuni pentru model>",   # rolul/regulile (system prompt)
    content="<conținutul de procesat>",     # textul efectiv (ex: corpul mailului)
    response_format="text",                  # "text" sau "json"
    model_hint=None,                         # None → Claude Haiku 4.5 (ieftin/rapid). Vezi §5
    temperature=0.0,
    max_tokens=2000,
    task="nume-task",                        # etichetă pt logging/audit
)
```

Răspuns normalizat (NU aruncă excepții niciodată — erorile vin în `error`):

```python
{
  "ok": True/False,
  "text": "...",        # textul brut al modelului ("" la eroare)
  "parsed": {...}|None, # JSON parsat când response_format="json"
  "usage": {"input_tokens":.., "output_tokens":.., "cost_usd":..}|None,
  "error": {"code":.., "message":..}|None,
  "task": "...",
}
```

**Pattern de folosire:**
```python
res = iris_ai.run_prompt(...)
if not res["ok"]:
    logger.warning("IRIS AI a eșuat: %s", res["error"])
    # degradează grațios — NU bloca fluxul principal de procesare email
else:
    rezultat = res["parsed"] if response_format == "json" else res["text"]
```

---

## 3. Exemplu: interpretarea intenției pe baza conținutului mailului

Folosește `response_format="json"` ca să primești date structurate. Pune în `system` schema dorită:

```python
SYSTEM_INTENT = (
    "Ești un clasificator de emailuri de business pentru o firmă de transport/logistică. "
    "Primești subiectul și corpul unui email și returnezi DOAR un JSON valid, fără text în plus, "
    "cu forma: {\"intent\": \"<una din: cerere_oferta|confirmare_comanda|factura|reclamatie|"
    "intrebare_status|programare|altul>\", \"confidence\": <0..1>, \"summary\": \"<o propoziție>\", "
    "\"actiune_sugerata\": \"<scurt>\"}."
)

def clasifica_intentie(email: dict) -> dict | None:
    content = f"Subiect: {email.get('subject','')}\n\n{email.get('body_text') or email.get('body_html') or ''}"
    res = iris_ai.run_prompt(
        system=SYSTEM_INTENT,
        content=content,
        response_format="json",
        temperature=0.0,
        max_tokens=300,
        task="intent_email",
    )
    if not res["ok"]:
        return None
    return res["parsed"]   # dict-ul deja parsat: {"intent":.., "confidence":.., ...}
```

Loc recomandat de apel: în pipeline-ul de procesare (`app/services/process_email.py::process_one`),
după detecția de phishing/spam, salvând rezultatul pe email (ex: o coloană `ai_intent jsonb`).
Rulează in-process → fără auth, fără HTTP.

---

## 4. Cum chemi din UI / extern (HTTP)

Doar dacă ai nevoie din frontend sau alt serviciu. Necesită JWT de admin (același ca restul API-ului).

```
POST /api/v1/ai/run-prompt
Authorization: Bearer <admin_jwt>
Content-Type: application/json

{ "content": "<text>", "system": "<instrucțiuni>", "response_format": "text",
  "model_hint": null, "temperature": 0.0, "max_tokens": 2000, "task": "etichetă" }
```
Răspuns: 200 cu `{ok, text, parsed, usage, ...}`; 502 dacă upstream/config pică (cu `error` structurat).

---

## 5. Reguli & limitări (important)

- **`content` (transcript) e plafonat la 48.000 caractere** (limita gateway-ului IRIS e 50k). Taie tu textul lung înainte (ex: corp mail prea mare).
- **`model_hint`**: dacă îl lași `None` → **Claude Haiku 4.5** (ieftin, rapid — bun pt clasificări/summary). Pentru taskuri mai grele trimite un id Anthropic valid, ex `claude-sonnet-4-6`. **Orice altă valoare (ex „gemma") e ignorată** — clientul trimite doar id-uri `claude-*`, altfel lasă default-ul.
- **`response_format="json"`**: dacă modelul nu produce JSON valid, `ok=False` cu `error.code="JSON_PARSE_ERROR"` și textul brut în `error`. Cere explicit „DOAR JSON valid" în `system`.
- **Degradare grațioasă**: la orice eroare funcția întoarce `ok=False` — niciodată excepție. Nu lega funcționalități critice (livrarea mailului) de răspunsul AI.
- **Cost & audit**: fiecare apel e logat în IRIS (`redaction_audit_log`, cu `app_name=Cargo360`). Haiku ≈ $1/M input, $5/M output (un mail tipic ≈ $0.0001). `usage.cost_usd` vine în răspuns.
- **Limba**: gateway-ul setează contextul pe `ro` implicit; scrie `system` în română pentru răspunsuri în română.

---

## 6. Checklist pentru un consumator nou

1. Scrie un `system` clar (rol + format de output; pentru date structurate cere JSON strict).
2. Cheamă `iris_ai.run_prompt(system, content, response_format=..., task="...")`.
3. Tratează `res["ok"]` false → log + fallback.
4. Pentru JSON, citește `res["parsed"]`.
5. Alege modelul: default Haiku; urcă la `claude-sonnet-4-6` doar dacă ai nevoie de calitate mai mare.
6. (Opțional) persistă rezultatul în DB.

Contact infra/activare: echipa IRIS. Cheia e deja validă (app `Cargo360`, id 19 în tabela IRIS `apps`).
```

---

## 7. Switch-uri CTS send flags (PS-2026-0128)

Câmpurile de clasificare trimise în feed-ul CTS pot fi controlate individual
din **UI → Setări → Conexiune API**, fără deploy. Util ca manetar de siguranță
la activarea/dezactivarea funcționalităților noi.

| Switch | Câmp(uri) afectat(e) în payload | Default |
|--------|--------------------------------|---------|
| **Categorie** | `categorie` | ON |
| **Departament** | `departament`, `departamentLabel` | ON |
| **Prioritate** | `prioritate`, `urgent` | ON |
| **Documente** | endpoint `GET /cts/get_email_documents` | ON |

**Comportament:**
- **ON** → câmpul apare cu valoarea reală în payload-ul CTS
- **OFF** → câmpul devine `null` în payload (CTS lasă câmpul necompletat)
- Pentru **Documente OFF**: endpoint-ul returnează `{"status": "disabled", "documents": []}`

**Stocare:** tabel `settings`, cheie `cts_send_flags` (JSONB).

**Endpoint admin:**
```
GET  /api/v1/settings/cts-send-flags  → starea curentă + defaults
PUT  /api/v1/settings/cts-send-flags  → { "send_categorie": false, ... }
```

**Notă:** Switch-urile funcționează **pe lângă** flag-ul master `cts_send_classification`
din `.env`. Pe producție, masterul e `false` → toate câmpurile sunt `null` indiferent
de switch-uri. Pe staging, masterul e `true` → switch-urile individuale sunt active.

### Câmpuri suplimentare pregătite pentru integrare CTS — faza 2 (în TEST pe staging)

Câmpurile de mai jos sunt **incluse în răspunsul endpoint-urilor CTS** chiar dacă AI-ul
nu le populează momentan. Structura e stabilă — CTS poate pregăti consumul imediat.
**Regula NULL:** `null` = „fără date, nu acționa". CTS nu trebuie să suprascrie valoarea
existentă din sistemul propriu dacă primește `null`; când AI-ul va produce date reale,
câmpul va conține un string/integer nenul.

**Câmpuri în payload mesaj — `GET /cts/get_emails`:**

| Câmp | Tip | Switch | Descriere |
|------|-----|--------|-----------|
| `categorie` | `string\|null` | `send_categorie` | `informatie`, `sesizare` sau `reclamatie` |
| `departament` | `string\|null` | `send_departament` | Cod departament intern (ex: `VANZARI`) |
| `departamentLabel` | `string\|null` | derivat | Etichetă human-readable pentru departament |
| `prioritate` | `integer\|null` | `send_prioritate` | `1` = normal, `2` = urgent |
| `urgent` | `boolean\|null` | derivat | `true` dacă `prioritate == 2` |

**Câmp per document — `GET /cts/get_email_documents`:**

| Câmp | Tip | Descriere |
|------|-----|-----------|
| `observatii_ai` | `string\|null` | Notă textuală AI — neconcordanțe/observații. Prezent întotdeauna (nu depinde de switch-uri). `null` → CTS ignoră. |


---

## 8. Câmpul `observatii_ai` pe extracții documente (OPS-2026-0125)

Coloana `observatii_ai text` pe tabelul `document_extractions` permite AI-ului
să noteze neconcordanțe detectate fără a bloca fluxul de procesare.
Un operator poate vedea imediat ce nu se potrivește, fără verificare manuală.

**Exemple de utilizare:**
- Nr. înmatriculare extras diferă față de cel din CTS
- Document aparținând altui vehicul dintr-un lot de 3 documente
- Pagina 2 dintr-un grup conține date de la un alt proprietar

**Expunere API:**
- `GET /cts/get_email_documents` → câmpul `observatii_ai` per document (null dacă necompletat)
- `GET /documents/extractions` + `GET /documents/extractions/{id}` → inclus automat în răspuns
- `PUT /documents/extractions/{id}` → `{ "observatii_ai": "text" }` — text liber; null/empty resetează câmpul

**Afișare UI:** în panoul de detalii document, dacă `observatii_ai` e completat, apare
un bloc albastru cu prefixul 🤖 **Observații AI** — vizibil înainte de câmpurile editabile.
În card-ul mic din lista kanban apare un indicator 🤖 cu tooltip (textul complet la hover).

**Setare programatică (viitor):** logica AI care detectează neconcordanțe (comparare
cu date CTS, cross-document validation) va face PUT pe `/documents/extractions/{id}`
cu `observatii_ai` completat, înainte ca documentul să fie validat de operator.


---

## 9. Endpoint `GET /cts/get_email_documents` — Referință completă

### Request

```
GET /api/v1/cts/get_email_documents?id_email={id_email}
Authorization: Bearer <token_cts>
```

| Parametru | Tip | Obligatoriu | Descriere |
|-----------|-----|-------------|-----------|
| `id_email` | integer | DA | ID-ul intern al emailului în Cargo360 |

### Răspuns — structură generală

```json
{
  "id_email": 34490,
  "received_at": "2026-06-23T12:24:40+00:00",
  "sent_to_cts_at": "2026-06-23T12:27:06+00:00",
  "now": "2026-06-29T12:06:37+00:00",
  "wait_deadline": "2026-06-23T12:32:06+00:00",
  "status": "ready",
  "documents": [ ... ]
}
```

**Câmpuri root:**

| Câmp | Tip | Descriere |
|------|-----|-----------|
| `id_email` | integer | ID email intern Cargo360 |
| `received_at` | string (ISO 8601) | Momentul primirii emailului |
| `sent_to_cts_at` | string (ISO 8601) | Momentul la care emailul a fost trimis spre CTS |
| `now` | string (ISO 8601) | Timestamp server la momentul răspunsului |
| `wait_deadline` | string (ISO 8601) | `sent_to_cts_at + 5 min` — deadline de așteptare pentru procesare |
| `status` | string | Starea emailului (vezi valorile de mai jos) |
| `documents` | array | Lista documentelor detectate și procesate |

**Valori posibile pentru `status`:**

| Valoare | Descriere |
|---------|-----------|
| `processing` | Documentele sunt încă în procesare — mai așteaptă |
| `ready` | Cel puțin un document e validat și `data`/`file` sunt disponibile |
| `manual_needed` | Documente în așteptarea validării manuale de operator |
| `no_documents` | Niciun document detectat în email |
| `disabled` | Switch-ul **Documente** e OFF din setări → `documents: []` |

### Structura unui document

```json
{
  "extraction_id": 3632,
  "attachment_id": 34941,
  "attachment_name": "CamScanner 23.06.2026 15.19.pdf",
  "content_type": "application/pdf",
  "is_part": true,
  "part_label": "Certificat de inmatriculare (Talon)",
  "category": "vehicul",
  "document_type_id": 1,
  "document_type": "Certificat de inmatriculare (Talon)",
  "confidence": 0.99,
  "doc_status": "validated",
  "reviewed": true,
  "reviewed_by": null,
  "observatii_ai": null,
  "data": {
    "Licence Plate (A.)": "TM-99-EKO",
    "Vin (E.)": "XLRTEF5100G403349"
  },
  "file": {
    "name": "Certificat de inmatriculare (Talon).pdf",
    "contentType": "application/pdf",
    "size": 265784,
    "contentBytes": "<base64>"
  }
}
```

> **Important:** câmpurile `data` și `file` apar **DOAR** când `doc_status == "validated"`.
> Pentru documente în procesare sau cu eroare, acestea lipsesc din răspuns.

**Câmpuri per document:**

| Câmp | Tip | Descriere |
|------|-----|-----------|
| `extraction_id` | integer | ID extracție intern Cargo360 |
| `attachment_id` | integer | ID atașament sursă |
| `attachment_name` | string | Numele original al fișierului atașat |
| `content_type` | string | MIME type (`application/pdf`, `image/jpeg` etc.) |
| `is_part` | boolean | `true` dacă e o bucată dintr-un PDF cu mai multe documente |
| `part_label` | string | Denumirea tipului de document detectat |
| `category` | string | `vehicul` / `sofer` / `contract` |
| `document_type_id` | integer | ID tip document — pentru câmpurile `data` vezi [CTS_DOCUMENT_TYPES_PAYLOAD.md](CTS_DOCUMENT_TYPES_PAYLOAD.md) |
| `document_type` | string | Denumire tip document (identică cu `part_label`) |
| `confidence` | float | Scor de încredere detecție (0..1) |
| `doc_status` | string | `validated` / `processing` / `manual_needed` / `failed` |
| `reviewed` | boolean | `true` dacă un operator a validat manual |
| `reviewed_by` | string\|null | Username operator care a validat; `null` dacă auto-validat |
| `observatii_ai` | string\|null | Notă AI (ex: neconcordanțe față de CTS). `null` = CTS ignoră câmpul |
| `data` | object | Câmpuri extrase — **prezent DOAR când `doc_status="validated"`** |
| `file.name` | string | Numele fișierului exportat |
| `file.contentType` | string | MIME type fișier |
| `file.size` | integer | Dimensiune în bytes |
| `file.contentBytes` | string | Conținut fișier în Base64 — **prezent DOAR când `doc_status="validated"`** |

### Răspuns când `send_documente = OFF`

```json
{
  "id_email": 34490,
  "received_at": "2026-06-23T12:24:40+00:00",
  "sent_to_cts_at": "2026-06-23T12:27:06+00:00",
  "now": "2026-06-29T12:06:37+00:00",
  "wait_deadline": "2026-06-23T12:32:06+00:00",
  "status": "disabled",
  "note": "Canalul de documente este dezactivat din setări.",
  "documents": []
}
```

### Note de integrare

- **Polling recomandat:** apelează la fiecare 30–60 secunde până când `status != "processing"`.
  `wait_deadline` indică momentul după care poți considera că extracția nu va mai avansa.
- **Filtrare după stare:** dacă vrei doar documentele confirmate de operator, filtrează
  după `doc_status == "validated"` — celelalte pot lipsi sau fi incorecte.
- **`data` poate fi `{}`** pentru tipuri fără câmpuri de extracție definite (ex: documente
  de tip Reprezentare, Proces verbal CargoBox, documente fără structură fixă).
- **`observatii_ai`** e prezent întotdeauna per document; dacă e `null`, CTS nu face nimic cu el.
- Pentru maparea completă `document_type_id` → câmpuri posibile în `data` + exemple JSON
  per fiecare dintre cele 34 tipuri, vezi **[CTS_DOCUMENT_TYPES_PAYLOAD.md](CTS_DOCUMENT_TYPES_PAYLOAD.md)**
  sau apasă butonul **⬇ Tipuri documente (34)** din modalul de integrare în aplicație.
