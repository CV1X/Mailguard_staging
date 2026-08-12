# Solicitare: endpoint IRIS pentru „Device Operations" (CTS) — ingestie în Cargo360

- **Proiect / app:** mailguard-staging
- **Solicitant (agent IRIS):** cristian-raul.covaci (L1)
- **Data:** 2026-07-02
- **Tip cerere:** cross_server (endpoint nou expus de IRIS Gateway)
- **Aprobator:** Razvan Perticas

## 1. Scop și flux

Cargo360 trebuie să preia acțiunile de „Device Operations" din **CTS** (instalări, calibrări,
intervenții, înlocuiri, demontări, mutări, periferice pe echipamentele montate la clienți) prin
IRIS Gateway, ca să le folosească în calculul de productivitate pentru **Suport 2** — mirror exact
pe cum se întâmplă azi cu mailurile (`/cts/ground-truth`), apelurile (`/cts/calls`) și task-urile
(`/cts/tasks`, deja live).

Am verificat: aceste 7 tipuri de acțiuni **NU apar** în feed-ul `/cts/tasks` deja existent (am
sondat live categoriile reale de task-uri pt departamentul Suport 2 — nimic din ce am găsit se
potrivește). Concluzia noastră: „Device Operations" e un subsistem CTS distinct, cu propriul jurnal
de acțiuni pe echipamente, nu o simplă categorie de task. De aceea cerem un endpoint nou, separat.

## 2. Metodă + cale sugerată

`GET /cts/device-operations` — pe **același IRIS Gateway** deja folosit de Cargo360 pentru
`/cts/ground-truth`, `/cts/calls`, `/cts/employees`, `/cts/tasks`.

**Polling**, nu push/webhook — consistent cu restul integrării (rulează la ~5 min, rolling sync).

## 3. Autentificare

Header `X-Mailguard-Key: <cheia existentă>` — **aceeași cheie** (`IRIS_MAILGUARD_API_KEY`) folosită
deja de celelalte 4 endpoint-uri de mai sus. Niciun secret nou de emis sau stocat.

## 4. Parametri de interogare

| Parametru    | Tip      | Obligatoriu | Descriere                                                          |
|--------------|----------|-------------|----------------------------------------------------------------------|
| `since`      | ISO8601  | Nu          | Filtrare rolling: doar acțiunile (re)actualizate după acest moment   |
| `limit`      | int      | Nu (implicit 2000) | Mărime pagină                                                |
| `action_type`| string   | Nu          | Filtrare pe tip acțiune (opțional, pt debugging manual)              |
| `department` | string   | Nu          | Filtrare pe departament (opțional, pt debugging manual)             |

Paginarea trebuie să respecte **ordine crescătoare pe `updated_at`** (sau echivalent), ca să putem
avansa cursorul între pagini — exact ca la celelalte feed-uri `/cts/*`.

## 5. Response (JSON)

```json
{
  "items": [
    {
      "operation_id": "DO-45821",
      "action_type": "instalare_noua",
      "status": "solved",
      "client_id": 10593,
      "assignee_email": "ion.popescu@cargotrack.ro",
      "department_slug": "suport-2",
      "device_serial": "BT50PRG",
      "descriere": "Instalare dispozitiv nou pe vehicul XYZ-123",
      "created_at": "2026-06-28T09:12:00Z",
      "updated_at": "2026-07-01T14:03:00Z"
    }
  ]
}
```

Câmpuri necesare per acțiune: `operation_id` (identificator STABIL, unic), `action_type`, `status`,
`client_id`, `assignee_email`, `department_slug` (sau echivalent), `device_serial`/identificator
echipament (dacă există), `descriere`, `created_at`, `updated_at`.

**Important**: `assignee_email` — preferăm **email direct**, ca să se poată face match pe
`employee_department_mapping.email` (la fel ca `cts_assignee_email` de la mailuri/apeluri și
`assignee_email` de la task-uri). Dacă CTS identifică operatorul doar printr-un ID intern, avem
nevoie și de un câmp `assignee_email` alături (sau un roster de mapare separat, ca la angajați).

## 6. Contract de sincronizare

Cursor pe `updated_at` (sau echivalent), avansat de Cargo360 pe baza valorii maxime din pagina
curentă (cu overlap mic ~1s), upsert idempotent pe `operation_id`. Fără plafon fix pe `limit` —
Cargo360 paginează automat până epuizează coada (pattern deja validat pe celelalte 3 feed-uri).

## 7. Coduri de eroare

Format consistent cu celelalte endpoint-uri `/cts/*`:
- `401` — `X-Mailguard-Key` lipsă/invalidă.
- `400` — parametri invalizi (`since` neparsabil, `limit` în afara intervalului acceptat).
- `500` — eroare internă IRIS/CTS (Cargo360 tratează ca eșec temporar, reîncearcă la următorul ciclu).

## 8. Exemplu de request

```
GET /cts/device-operations?since=2026-07-01T00:00:00Z&limit=2000
Host: iris.cargotrack.ro
X-Mailguard-Key: <cheia existentă>
```

Exemplu de response — vezi secțiunea 5.

## 9. Întrebări deschise pentru Razvan

1. **Care sunt denumirile EXACTE (enum complet)** folosite intern în CTS pentru cele 7 tipuri de
   acțiuni cerute de business: instalare nouă, calibrare, intervenție, înlocuire, demontare,
   mutare, periferice? (avem nevoie de valorile literale ca să le mapăm corect la ingestie)
2. **Ce statusuri există** și care e/sunt „terminale" (echivalentul „solved"/"closed" la task-uri)?
3. **Există un identificator de echipament** (serie, IMEI, asset ID) asociat fiecărei acțiuni? Dacă
   da, sub ce nume de câmp?
4. **`assignee_email` e disponibil direct**, sau operatorul e identificat doar printr-un ID intern
   (caz în care avem nevoie de un roster de mapare, ca la task-uri)?
5. **Departamentul vine direct pe record**, sau se deduce doar din departamentul assignee-ului?
6. **Volum estimat/lună** pentru Suport 2 (ca să dimensionăm corect paginarea/plafonul de sync)?

## 10. Context suplimentar

Aceste date alimentează un nou obiectiv de productivitate pentru Suport 2 (mirror pe modelul deja
funcțional la Suport 1: mailuri + task-uri + apeluri, fiecare cu limită și pondere proprii — vezi
modulul „Productivitate" din Cargo360). Modulul „Device Operations" e deja pregătit în meniul
Cargo360 (tab nou, UI placeholder) — sincronizarea reală pornește automat, fără redeploy, imediat
ce endpoint-ul de mai sus e disponibil.
