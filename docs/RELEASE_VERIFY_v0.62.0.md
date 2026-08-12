# Verificare post-release — Cargo360 v0.62.0

**Pentru agentul CC de pe producție (`cargo360`).** Document de verificare: confirmă că tot ce a
fost livrat pe staging s-a propagat corect pe producție după apăsarea butonului Release.

- **Sursă:** `mailguard-staging` (`/opt/iris-mailguard`), versiune **0.62.0**
- **Livrat:** 2026-07-30 · **Autor:** agent CC staging, la cererea lui Raul Covaci
- **Natura livrării:** modificări UI/UX + 1 migrație DB (aditivă) + 2 prompturi AI
- **Verificare anterioară:** double-check complet pe staging, 3 bug-uri găsite și reparate (vezi §7)

> ⚠️ Acest document e o **listă de verificare read-only**. Nu modifica nimic pe producție pe baza
> lui. Dacă o verificare eșuează, raportează exact ce a eșuat — nu „repara" singur.

---

## 1. Verificare rapidă (dacă ai 2 minute, rulează doar asta)

```bash
# 1. versiunea a ajuns pe prod
curl -s https://<host-prod>/api/v1/health | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['version'],d['status'],d['checks']['database'])"
# AȘTEPTAT: 0.62.0 healthy ok

# 2. migrația s-a aplicat
<psql-prod> -c "SELECT filename, applied_at FROM _release_migrations WHERE filename='20260730_doc_types_cargobox_etoll.sql';"
# AȘTEPTAT: 1 rând

# 3. cele 4 tipuri de documente există
<psql-prod> -c "SELECT count(*) FROM document_types WHERE created_by='iris-ux-20260730' AND status='active';"
# AȘTEPTAT: 4

# 4. filtrul de perioadă funcționează
curl -s -o /dev/null -w "%{http_code}\n" "https://<host-prod>/api/v1/stats/dashboard?date_from=2026-07-01&date_to=2026-07-20"
# AȘTEPTAT: 200

# 5. graficele sunt bare, nu linii
curl -s https://<host-prod>/vendor/mg-app.js | grep -c "type: 'line'"
# AȘTEPTAT: 0
```

Dacă toate 5 trec, propagarea de bază e OK. Continuă cu §2–§6 pentru verificarea completă.

---

## 2. Fișiere care trebuie să fie modificate pe producție

11 fișiere. Verifică prezența modificărilor (nu compara md5 cu staging — pot diferi legitim dacă
prod are hotfix-uri proprii; verifică prezența markerilor).

| Fișier | Marker de verificat (`grep`) |
|---|---|
| `app/api/v1/health.py` | `_range_filter`, `_day_window`, `_valid_date` |
| `app/api/v1/cts_tasks_training.py` | `_task_filters`, `closed_not_solved`, `LEFT JOIN LATERAL`, `device_imei_text` |
| `app/api/v1/device_ops.py` | `_ops_filters`, `_valid_date` |
| `app/api/v1/emails.py` | `date_from`, `from datetime import date as _date` |
| `app/api/v1/calls_analytics.py` | `total_duration_seconds`, `pattern=r"^\d{4}-\d{2}-\d{2}$"` |
| `app/services/satisfaction_engine.py` | `MOTIVE ECONOMICE / EXTERNE` |
| `app/services/interaction_analyzer.py` | `MOTIVE ECONOMICE / EXTERNE` (de **2** ori — email + apel) |
| `app/ui/vendor/mg-app.js` | `DateRangeFilter`, `printReportPdf`, `rangeQS`, `TASK_STATUS_LABELS` |
| `VERSION` | `0.62.0` |
| `CHANGELOG.md` | secțiunea `## v0.62.0` |
| `migrations/20260730_doc_types_cargobox_etoll.sql` | fișierul există |

```bash
# script de verificare markeri
cd /opt/iris-mailguard
for m in "_range_filter:app/api/v1/health.py" "_day_window:app/api/v1/health.py" \
 "_valid_date:app/api/v1/health.py" "_task_filters:app/api/v1/cts_tasks_training.py" \
 "closed_not_solved:app/api/v1/cts_tasks_training.py" "LEFT JOIN LATERAL:app/api/v1/cts_tasks_training.py" \
 "_ops_filters:app/api/v1/device_ops.py" "total_duration_seconds:app/api/v1/calls_analytics.py" \
 "MOTIVE ECONOMICE:app/services/satisfaction_engine.py" "DateRangeFilter:app/ui/vendor/mg-app.js" \
 "printReportPdf:app/ui/vendor/mg-app.js" "TASK_STATUS_LABELS:app/ui/vendor/mg-app.js"; do
  pat="${m%%:*}"; f="${m##*:}"
  n=$(grep -c "$pat" "$f" 2>/dev/null || echo 0)
  [ "$n" -gt 0 ] && echo "OK   $pat -> $f ($n)" || echo "LIPSA $pat -> $f"
done
# ATENȚIE: în interaction_analyzer.py marker-ul trebuie să apară de 2 ori (ambele prompturi)
grep -c "MOTIVE ECONOMICE" app/services/interaction_analyzer.py   # AȘTEPTAT: 2
```

**Atenție la `vendor/`:** pe staging, `deploy.sh` exclude directorul `vendor/` din rsync, iar
`mg-app.js` se propagă cu un script separat (`deploy_vendor.sh`). **Verifică explicit că bundle-ul
de frontend a ajuns pe prod** — e cea mai probabilă piesă lipsă:

```bash
curl -s https://<host-prod>/vendor/mg-app.js -o /tmp/prod.js
node --check /tmp/prod.js && echo "sintaxa OK"
for p in DateRangeFilter printReportPdf rangeQS TASK_STATUS_LABELS device_number backFromClient; do
  printf "%s: %s\n" "$p" "$(grep -c "$p" /tmp/prod.js)"
done
# AȘTEPTAT: toate > 0. Dacă sunt 0 => frontend-ul NU s-a propagat, deși backend-ul da.
```

---

## 3. Migrația DB — singura schimbare de date

**Fișier:** `migrations/20260730_doc_types_cargobox_etoll.sql`

Inserează 4 tipuri de documente, **fără șablon** (le încarcă Raul manual din UI). Aditivă și
idempotentă. **Nu modifică schema** — doar `INSERT`.

```bash
# 1. înregistrată
<psql-prod> -c "SELECT filename, applied_at FROM _release_migrations WHERE filename LIKE '%cargobox_etoll%';"

# 2. cele 4 tipuri, cu has_sample=false (normal — șabloanele se urcă manual)
<psql-prod> -c "SELECT id, category, name, (sample_path IS NOT NULL) AS has_sample, enabled, status
                FROM document_types WHERE created_by='iris-ux-20260730' ORDER BY id;"
```

**Așteptat — exact 4 rânduri, toate `category='contract'`, `has_sample=f`, `enabled=t`, `status=active`:**
- `CUI / Extras pe contract carGObox sau ETOLL`
- `Anexa 2 - contract carGObox`
- `Anexa 3 - contract carGObox`
- `Anexa 4 - contract carGObox`

> `category='contract'` e intenționat: CUI = certificat al **firmei**, nu al vehiculului, și e cerut
> la dosarul de contract. Categoriile permise de aplicație sunt doar `vehicul|sofer|contract`.

**Ce NU trebuie să se fi schimbat:**
```bash
# "Act de identitate" (buletin/pașaport) trebuie să existe NEATINS — exista deja
<psql-prod> -c "SELECT id, category, name FROM document_types WHERE name='Act de identitate';"
# AȘTEPTAT: 1 rând, category='sofer' (pe staging avea id=2)

# schema document_types neatinsă
<psql-prod> -c "SELECT count(*) FROM information_schema.columns WHERE table_name='document_types';"
# AȘTEPTAT: 20

# coloana shift NU a fost ștearsă (s-a scos doar din UI)
<psql-prod> -c "SELECT column_name FROM information_schema.columns
                WHERE table_name='employee_department_mapping' AND column_name='shift';"
# AȘTEPTAT: 1 rând ('shift')
```

**Idempotență (opțional, sigur de rulat):** re-rularea migrației trebuie să dea `INSERT 0 0`.
`ON CONFLICT` țintește indexul unic **parțial** `(category, lower(name)) WHERE status='active'`.

**Dacă migrația NU s-a aplicat:** nu o rula manual. Raportează — mecanismul de Release
(`scripts/migrate.sh` + `_release_migrations`) trebuie investigat.

---

## 4. Verificare funcțională — endpoint-uri

### 4.1 Filtru de perioadă: date valide → 200

`date_to` e **inclusiv** (`< date_to + 1 zi`). Fără parametri, comportamentul e cel vechi.

```bash
for ep in stats/dashboard stats/overview stats/calls-dashboard stats/daily stats/daily-category \
          stats/calls-daily stats/calls-daily-category stats/tasks-daily stats/tasks-overview \
          stats/calls-overview stats/document-processing emails; do
  c=$(curl -s -m 25 -o /dev/null -w "%{http_code}" \
      "https://<host-prod>/api/v1/$ep?date_from=2026-07-16&date_to=2026-07-25")
  echo "$c  $ep"
done
# AȘTEPTAT: 200 pe toate 12
```

### 4.2 Filtru de perioadă: date invalide → 400/422 (NU 500)

Acesta a fost un **bug reparat** — dacă prod dă 500, patch-ul de validare nu s-a propagat.

```bash
for ep in stats/dashboard stats/overview stats/calls-dashboard stats/daily stats/tasks-overview \
          stats/document-processing emails; do
  c=$(curl -s -m 25 -o /dev/null -w "%{http_code}" "https://<host-prod>/api/v1/$ep?date_from=BAD")
  echo "$c  $ep"
done
# AȘTEPTAT: 400 sau 422 pe toate. 500 = PROBLEMĂ, raportează.
```

### 4.3 Compatibilitate: fără parametri → comportament vechi

```bash
for ep in health stats/dashboard stats/overview "emails?page=1" "stats/daily?days=7" \
          "stats/document-processing?days=30"; do
  echo "$(curl -s -m 25 -o /dev/null -w '%{http_code}' "https://<host-prod>/api/v1/$ep")  $ep"
done
# AȘTEPTAT: 200 pe toate
```

### 4.4 KPI apeluri: câmp nou `total_duration_seconds`

```bash
curl -s "https://<host-prod>/api/v1/stats/calls-dashboard?date_from=2026-07-16&date_to=2026-07-25" \
 | python3 -c "import json,sys;d=json.load(sys.stdin);print('total',d.get('total'),'IN',d.get('inbound'),'OUT',d.get('outbound'),'ore',round((d.get('total_duration_seconds') or 0)/3600,1))"
# AȘTEPTAT: total_duration_seconds prezent (nu None). Dacă lipsește => calls_analytics/health nu s-au propagat.
```

### 4.5 Corectitudine numerică — API vs DB

Compară API cu interogare directă. **Alege un interval cu date pe prod** (înlocuiește datele).

```bash
API=$(curl -s "https://<host-prod>/api/v1/stats/dashboard?date_from=2026-07-16&date_to=2026-07-25" \
      | python3 -c "import json,sys;print(json.load(sys.stdin)['total'])")
DB=$(<psql-prod> -t -A -c "SELECT count(*) FROM emails
      WHERE received_at >= DATE '2026-07-16' AND received_at < DATE '2026-07-26';")
echo "API=$API DB=$DB"
# AȘTEPTAT: identice (atenție: DB folosește '2026-07-26' pentru că date_to e inclusiv)
```

### 4.6 Paritate listă vs statistici (KPI reactive)

Cerință explicită: KPI-urile de sus trebuie să reflecte filtrele din tabel, nu cumulatul.
Endpoint-urile sunt admin-only (401 fără token) — verifică prin SQL, replicând helperii.

```bash
# Task-uri: /list și /stats trebuie să dea ACELAȘI total sub aceleași filtre
<psql-prod> -c "
SELECT (SELECT count(*) FROM cts_task_ground_truth gt
        LEFT JOIN employee_department_mapping edm ON edm.id = gt.assignee_employee_id
        LEFT JOIN clients cl ON cl.iris_client_id = gt.client_id
        WHERE 1=1 AND gt.department='taxe_drum'
          AND gt.cts_created_at >= CAST('2026-07-16' AS date)
          AND gt.cts_created_at < (CAST('2026-07-25' AS date) + INTERVAL '1 day')) AS total_lista,
       (SELECT count(*) FROM cts_task_ground_truth gt
        WHERE 1=1 AND gt.department='taxe_drum'
          AND gt.cts_created_at >= CAST('2026-07-16' AS date)
          AND gt.cts_created_at < (CAST('2026-07-25' AS date) + INTERVAL '1 day')) AS total_stats;"
# AȘTEPTAT: total_lista = total_stats
```

### 4.7 `LEFT JOIN LATERAL` pe device — nu trebuie să dupliceze rânduri

Un `LEFT JOIN` simplu ar fi duplicat task-urile (același IMEI apare în până la 9 operațiuni).

```bash
<psql-prod> -c "
SELECT (SELECT count(*) FROM cts_task_ground_truth) AS fara_join,
       (SELECT count(*) FROM cts_task_ground_truth gt
        LEFT JOIN LATERAL (SELECT d.device_serial FROM device_operations d
          WHERE d.device_imei = substring(COALESCE(gt.description,'') from '\\m[0-9]{14,17}\\M')
          ORDER BY d.cts_updated_at DESC NULLS LAST, d.id DESC LIMIT 1) dv ON TRUE) AS cu_join;"
# AȘTEPTAT: fara_join = cu_join (EXACT). Diferență = duplicare, raportează imediat.
```

### 4.8 Status task: `closed` ≠ `solved`

```bash
<psql-prod> -c "SELECT status, count(*) FROM cts_task_ground_truth GROUP BY 1 ORDER BY 2 DESC;"
# Verifică apoi în UI: task-urile cu status 'closed' afișează badge
# „închis (nerezolvat)", NU „rezolvat", și sunt numărate separat în KPI-uri.
```

---

## 5. Verificare frontend (necesită browser / smoke-test)

Pe staging **nu s-a putut face verificare vizuală** (smoke-test blocat de sandbox, Playwright
absent, token JWT redactat). **Dacă ai acces la smoke-test pe prod, rulează-l** — e singura zonă
neacoperită de verificarea de pe staging.

| # | Modul | Ce verifici | Așteptat |
|---|---|---|---|
| 1 | Dashboard | Filtru „Perioada" sus | Două câmpuri dată + Aplică; la aplicare se schimbă TOATE secțiunile (emailuri, apeluri, task-uri, documente) |
| 2 | Dashboard | KPI Task-uri | Card nou „Închise nerezolvate", separat de „Rezolvate" |
| 3 | Utilizatori | Tabel angajați | **NU** există coloana „Schimb"; există câmp de căutare + filtru departament |
| 4 | Utilizatori | Caută „brasovean" (fără diacritice) | Găsește „Brașovean" |
| 5 | Rapoarte | Graficele de evoluție | **Bare**, nu linii, în toate 3 taburile |
| 6 | Rapoarte | Secțiunea Acuratețe | **Nu mai există** (nici la Email-uri, nici la Apeluri, nici per tip document) |
| 7 | Rapoarte | Buton „Raport PDF" | Deschide fereastră de print cu KPI + grafice (ca imagini, nu goale) + perioada în antet |
| 8 | Rapoarte | Schimbă tabul cu perioadă activă | Perioada se păstrează între taburi |
| 9 | Satisfacție | „View" pe un client → detaliu | Buton „**Înapoi la Satisfacție clienți**" (nu „Lista clienți"); duce înapoi la Satisfacție |
| 10 | Emailuri | Filtru „Recepționat" | Aceeași dată în ambele câmpuri = mailurile dintr-o singură zi |
| 11 | Task-uri | Coloană „Nr. device" | Prezentă; numerele extrase au `*` când nu sunt confirmate (vezi §8) |
| 12 | Task-uri | Schimbă tip/departament | Cifrele din capul paginii se schimbă (nu rămân pe cumulat) |
| 13 | Device Operations | Filtru „Creat" | Informațiile de sus se recalculează la selectarea intervalului |
| 14 | Apeluri → Analitice | KPI | Nr. apeluri, **IN**, **OUT**, **Total ore**, Durata medie, Răspuns |
| 15 | Apeluri → Analitice | Schimbă departamentul | Graficul se actualizează (bug #3 reparat — vezi §7) |
| 16 | Procesare documente → Tipuri | Cele 4 tipuri noi | Prezente, fără șablon încărcat |
| 17 | Toate | Light + dark mode | Axele/grila graficelor lizibile în ambele (tokeni CSS, nu hex) |

**Consolă browser:** 0 erori JS pe paginile atinse (Dashboard, Rapoarte, Utilizatori, Emailuri,
Task-uri, Device Ops, Apeluri, Satisfacție, Procesare documente).

---

## 6. Prompturi AI — efect întârziat, nu e bug

Două prompturi modificate. Regula: **motivele economice/externe NU scad satisfacția și nu marchează
clientul ca nemulțumit/la risc** — insolvență, faliment, lipsă de bani, vânzarea firmei sau a
camioanelor, accident/daună totală, încheierea unui leasing, restructurare, sezonalitate.

```bash
grep -c "MOTIVE ECONOMICE" app/services/satisfaction_engine.py     # AȘTEPTAT: 2
grep -c "MOTIVE ECONOMICE" app/services/interaction_analyzer.py    # AȘTEPTAT: 2 (email + apel)
```

**De ce în două fișiere:** `interaction_analyzer.py` generează flag-ul `mentiune_reziliere`, iar acel
flag **forța automat segmentul „critic"**, ocolind decizia AI din motorul de scor. Fără regula din
al doilea fișier, corectura n-ar fi avut efect. **Ambele sunt obligatorii.**

**Comportament așteptat după release:**
- Schimbarea promptului modifică hash-ul de versiune (`_model_version()`) → interacțiunile se
  **re-analizează automat**, progresiv. Scorurile nu se schimbă instantaneu — **normal, nu e bug**.
- Pentru efect imediat pe un client: butonul de estimare satisfacție din pagina clientului.
- Cost AI: re-analiza consumă interogări. Dacă volumul de pe prod e mare, monitorizează costul în
  primele zile (Dashboard → „Costuri AI").

---

## 7. Bug-uri reparate pe staging — verifică-le explicit pe prod

Găsite la double-check. Dacă reapar pe prod, patch-ul nu s-a propagat.

| # | Bug | Test pe prod | Așteptat |
|---|---|---|---|
| 1 | Dată invalidă → HTTP 500 (Postgres `DataError` din `CAST`) | §4.2 | 400/422, nu 500 |
| 2 | Rapoarte → Email-uri se blocau pe „Se încarcă" dacă `/cts-training/stats` eșua | Deschide Rapoarte → Email-uri | Se încarcă normal; la eroare apare buton „Reîncearcă" |
| 3 | Graficele afișau date vechi la schimbarea unui filtru care păstra aceleași zile | §5 pct. 15 | Graficul se actualizează |

Bug 1 și 3 erau **preexistente** în `calls_analytics.py` / `MultiLineChart` (nu introduse de această
livrare), dar reparate acum. Bug 2 a fost introdus de scoaterea acurateței și reparat.

---

## 8. Limitări cunoscute — NU sunt bug-uri, nu le „repara"

1. **Nr. device (Task-uri) — acoperire parțială.** CTS **nu** expune numărul devicelui ca câmp și nu
   există cheie de legătură cu `device_operations` (verificat: 0 potriviri pe `operation_id` din
   30.017 task-uri). Se extrage din descriere, unde apare ca IMEI de 14–17 cifre — pe staging ~255
   din 21.251 task-uri de device. Restul afișează „—". Numerele neconfirmate în `device_operations`
   sunt marcate cu `*`. **Acoperire completă cere o schimbare în CTS**, nu în Cargo360.
2. **Șabloanele celor 4 tipuri de documente lipsesc intenționat.** Raul le încarcă manual din UI.
   `has_sample=false` e starea corectă.
3. **Selectorul „7/30/60/90 zile" din Rapoarte** e ascuns cât timp e activă o perioadă
   personalizată — intenționat, ca să nu pară două filtre în conflict.
4. **Endpoint-urile de acuratețe** (`/cts-training/accuracy-daily`, `/cts-calls-training/stats`)
   rămân funcționale în backend, dar nu mai sunt afișate. Nu le șterge.
5. **`shift` (Utilizatori)** rămâne în DB și în API — s-a scos doar din interfață, la cererea
   utilizatorului (0 valori setate pe staging).

---

## 9. Raport final cerut

Raportează în această formă:

```
VERIFICARE POST-RELEASE v0.62.0 — <data>

Versiune API prod:        [0.62.0 / alta: ___]
Migrație aplicată:        [DA / NU]
4 tipuri documente:       [4 / alt număr: ___]
Schema neatinsă:          [DA / NU]  (20 coloane document_types, shift prezentă)
Frontend propagat:        [DA / NU]  (markeri în /vendor/mg-app.js)
Date valide → 200:        [__/12]
Date invalide → 400/422:  [__/7]   (500 = bug 1 nepropagat)
Fără parametri → 200:     [__/6]
API vs DB (numeric):      [MATCH / MISMATCH: ___]
Paritate listă/stats:     [MATCH / MISMATCH: ___]
LATERAL fără duplicare:   [MATCH / MISMATCH: ___]
Prompturi (2+2 markeri):  [DA / NU]
Verificare vizuală:       [__/17 puncte §5]  sau [NEEFECTUATĂ — motiv: ___]
Erori în loguri:          [0 / ___]

PROBLEME GĂSITE: <listă sau „niciuna">
```

**Dacă ceva eșuează:** raportează exact ce, cu output-ul comenzii. **Nu aplica fix-uri pe producție**
fără aprobarea lui Razvan — inclusiv dacă pare o corectură evidentă.

---

## 10. Rollback

Dacă e nevoie de revenire:
- **Cod:** mecanismul de Release / restore din `storage/backups/` (snapshot pre-release).
- **Migrația:** aditivă, nu necesită rollback. Dacă totuși e cerut, dezactivarea celor 4 tipuri e
  reversibilă și non-distructivă:
  ```sql
  UPDATE document_types SET status='deleted', updated_at=now()
   WHERE created_by='iris-ux-20260730';
  ```
  Nu face `DELETE` — ar rupe referințele din `document_extractions` dacă s-au procesat documente.
- **Prompturi:** revenirea la textul anterior schimbă din nou hash-ul → re-analiză încă o dată
  (cost AI). Consultă Razvan înainte.
