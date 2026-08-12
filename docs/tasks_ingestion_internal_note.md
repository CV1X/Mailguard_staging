# Notă internă MG — ingestia task-urilor din CTS

Modelată 1:1 pe modulul „Mailuri CTS" (`cts_ground_truth` + `app/services/cts_groundtruth_sync.py`),
arhitectură deja validată în producție. Scop: acest document ghidează implementarea, după ce Razvan
confirmă/expune endpoint-ul din `OUTBOX_tasks_endpoint.md`. Nu e cod — e planul de implementare.

## 1. Tabelă nouă — `cts_task_ground_truth`

Mirror pe `cts_ground_truth`, adaptat pt task-uri:

```sql
CREATE TABLE IF NOT EXISTS cts_task_ground_truth (
  id                bigserial PRIMARY KEY,
  task_id           text NOT NULL,
  tip               varchar(64),
  status            varchar(32),
  client            text,
  operator_email    varchar(320),
  operator_nume     text,
  descriere         text,
  data_creare       timestamptz,
  data_actualizare  timestamptz,
  entitate_tip      varchar(20),      -- 'mail' | 'apel' | 'contract' | NULL
  entitate_ref      text,             -- message_id / call_id / etc.
  prioritate        varchar(16),
  source            varchar(20) DEFAULT 'iris_sync',
  raw               jsonb,
  fetched_at        timestamptz DEFAULT now(),
  UNIQUE (source, task_id)
);
CREATE INDEX IF NOT EXISTS idx_task_gt_operator  ON cts_task_ground_truth (lower(operator_email));
CREATE INDEX IF NOT EXISTS idx_task_gt_status     ON cts_task_ground_truth (status);
CREATE INDEX IF NOT EXISTS idx_task_gt_entitate   ON cts_task_ground_truth (entitate_ref) WHERE entitate_ref IS NOT NULL;
```

Idempotent pe `task_id` (`UNIQUE (source, task_id)`, la fel ca `cts_ground_truth` pe
`(source, message_id)`). Dacă `entitate_tip='mail'`, `entitate_ref` = `message_id`, folosit pt
matching cu `emails` (același pattern ca `_match_email_id` din sync-ul de mailuri).

## 2. Serviciu nou — `app/services/cts_tasks_sync.py`

Structură identică cu `cts_groundtruth_sync.py`:
- `GATEWAY_PATH = "/cts/tasks"`, canal `_fetch_from_gateway` (reutilizează `iris_api_url` +
  `IRIS_MAILGUARD_API_KEY`, header `X-Mailguard-Key` — **fără cod nou de autentificare**).
- `sync_tasks_paged(since=None, batch=2000, max_batches=40)` — paginat pe cursor `data_actualizare`,
  overlap 1s pe graniță, upsert `ON CONFLICT (source, task_id) DO UPDATE`.
- `sync_recent(hours=24)` — PASS1 (fereastră proaspătă) + PASS2 (backfill pending, plafonat la
  168h) — identic cu mailurile, ca să evităm din start incidentul de trunchiere de coadă din
  30 iunie.
- Endpoint `/cts-training/tasks/sync-recent` (analog `/cts-training/sync-recent`), thread background,
  lock non-blocant (`sync_recent_guarded`).

## 3. Rezolvare assignee absent din Cargo360 (FOLLOW-UP, nu implementare acum)

Azi, `iris_employee_sync.py` importă DOAR angajați din departamente în `VALID_DEPARTMENTS`
(`suport_1/2/3, taxe_drum, contabilitate, mobilitate, recuperare_tva, comercial`) — restul (HR,
Marketing, Management etc.) sunt SKIP (`n_skip_dept`), la cererea explicită anterioară a userului.

**Nu e nevoie de endpoint IRIS nou** — `/cts/employees` întoarce deja profilul complet (inclusiv
`planned_leave`/`leave_requests`) pentru orice angajat, indiferent de departament; filtrarea e strict
pe partea Cargo360 (`_norm_dept` întoarce `None` dacă departamentul nu e în whitelist → skip).

Plan de fix (fază 2, după ce avem date reale de task-uri):
- La sync-ul de task-uri, dacă `operator_email` nu există în `employee_department_mapping`, se
  declanșează un import punctual din `/cts/employees` pentru acel email (folosind funcția deja
  existentă `fetch_employees`), **chiar dacă departamentul lui nu e în `VALID_DEPARTMENTS`** — fie
  printr-o excepție punctuală („are task-uri active → se importă oricum"), fie prin extinderea
  whitelist-ului cu departamentele care apar efectiv pe task-uri.
- Concediile (`planned_leave`) ale acestor angajați trebuie importate la fel — altfel calculul de
  `ore_disponibile` din modulul Productivitate (obiectiv `tip='task'`) ar fi eronat pentru ei.

## 4. Procesare

- Încadrare task pe categorie/tip (analog `ai_category` la mailuri, dar aici tip-ul vine deja de la
  CTS — nu necesită clasificare AI, doar normalizare/mapare).
- Comparare cu adevărul de teren CTS (dacă Cargo360 are propria logică de rutare/status pt task-uri
  în viitor) — modelată pe `CtsTrainingPanel` (matrice confuzie AI vs CTS).
- Alimentare modul Productivitate: `productivity_objective` are deja `tip='task'` pregătit în schema
  curentă (`PROD_TIP_OPTIONS` include `'task'` în UI) — odată ce există date reale, se poate configura
  un obiectiv general pt task-uri exact ca la emailuri, fără nicio schimbare de schemă.

## 5. Consum (UI)

Înlocuiește placeholder-ul `TaskuriPage` (`app/ui/index.html`, azi doar text „în curs de dezvoltare").
Model: `CtsTrainingPanel` — tabel task-uri (filtrabil pe status/departament/operator), stats sumare
(volum, pe status, pe operator), buton „Sincronizează acum" (analog sync-recent de la mailuri/apeluri).

## 6. Ce rămâne de făcut, în ordine

1. Trimis `OUTBOX_tasks_endpoint.md` lui Razvan → aștept răspuns la întrebările deschise.
2. Migrație `cts_task_ground_truth` (aditivă, idempotentă) — imediat ce avem confirmarea structurii
   reale a payload-ului (poate necesita ajustări de coloane față de schema propusă aici).
3. `app/services/cts_tasks_sync.py` + endpoint sync.
4. Fix assignee absent (secțiunea 3) — necesar înainte ca datele de task-uri să fie complete/corecte.
5. UI `TaskuriPage` (tabel + stats + sync).
6. Conectare la modulul Productivitate (`tip='task'`), odată ce există volum real de date.
