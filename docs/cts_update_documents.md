# CTS — `POST /cts/update_documents` (trasabilitate documente)

**Status:** implementat în Cargo360 (staging, v2.2.1). **Necesită implementare pe partea CTS.**
**Versiune document:** 2026-08-12.
**Tichete:** CCTS-5308 (Trasabilitate documente MailGuard în CTS), CCTS-5071 (Asociere automată).

---

## Pe scurt (pentru PO / Team Leader)

**Ce se schimbă pentru utilizator:** nimic în fluxul zilnic. Nu apar butoane noi, nu se modifică
modul în care se procesează emailurile sau documentele. Singura schimbare vizibilă e un bloc nou de
cifre pe pagina **Procesare documente**.

**Ce răspuns primim, pe care azi nu-l avem:**

| Întrebare | Unde apare |
|---|---|
| Din documentele extrase, câte pleacă efectiv spre CTS? | card „Trimise spre CTS" |
| Din cele trimise, câte ajung atașate pe entitate? | card „Salvate pe entitate" |
| Din cele atașate, câte le șterg operatorii pentru că asocierea a greșit? | card „Șterse de operatori" |
| Cum stă fiecare tip de document în parte? | bara pe categorii: șofer / vehicul / contract |

**Ce trebuie făcut ca cifrele să apară:** partea CTS trebuie să apeleze endpoint-ul descris mai jos
(vezi secțiunea finală, „De implementat pe partea CTS"). Până atunci pagina arată zero — nu e o
defecțiune, e lipsa datelor de retur.

**Cât de repede se văd rezultatele:** confirmările de salvare vin imediat după procesarea fiecărui
email; ștergerile vin o dată pe zi, în lot (04:00 UTC). Deci procentul de documente șterse are un
decalaj normal de până la 24 de ore.

**Ce se întâmplă cu istoricul:** cifrele se acumulează în timp și **nu se pierd** la curățenia
zilnică a documentelor. Poți urmări evoluția lună de lună, care era scopul cerut în tichet.

---

## De ce există

Astăzi Cargo360 trimite documente către CTS prin `GET /cts/get_email_documents` și **nu află niciodată
ce s-a întâmplat cu ele**. Nu se poate răspunde la întrebările pentru care a fost cerut epicul:

- Din documentele trimise, ce procent ajunge efectiv atașat pe entitatea corectă (contract / șofer / vehicul)?
- Din cele atașate, ce procent e șters ulterior de un operator, pentru că asocierea automată a greșit?

Acest endpoint e canalul de retur. Fără el, statistica de pe pagina „Procesare documente" rămâne goală.

---

## Formatul fișierelor livrate (garanții Cargo360)

Constrângeri impuse de CTS, aplicate la livrare în `GET /cts/get_email_documents` → `documents[].file`:

| Categorie | Format garantat | Mărime |
|---|---|---|
| `vehicul` | **PDF întotdeauna** | ≤ 1,6 MB |
| `contract` | **PDF întotdeauna** | ≤ 1,6 MB |
| `sofer` | PDF sau imagine (PNG/JPEG) | ≤ 1,6 MB |
| *fără categorie* | **PDF întotdeauna** | ≤ 1,6 MB |

Documentele fără categorie (clasificarea automată nu a reușit) sunt tratate ca PDF-obligatoriu, nu
exceptate. Măsurat pe staging: 3 din 39 de documente validate aveau categoria goală, printre care
două taloane — deci exact documentele neclasificate ar fi scăpat de regulă dacă ar fi decis-o
categoria. `sofer` rămâne singura excepție unde se acceptă imagine.

Pentru vehicul și contract, orice imagine (inclusiv decupajul dintr-un PDF, care se produce ca JPEG)
e convertită la PDF înainte de livrare. Pentru șofer, imaginea se păstrează ca atare dacă încape în
limită; dacă e prea mare, se convertește la PDF, fiindcă acolo conversia e și mecanismul de compresie.

Reducerea sub 1,6 MB se face în trepte: compresie fără pierderi, apoi calitate JPEG descrescătoare,
apoi reducerea rezoluției. Pentru PDF-uri cu pagini scanate (care nu scad prin compresie obișnuită,
imaginile fiind deja comprimate) paginile se re-randează la rezoluție redusă — se pierde stratul de
text, dar fișierul intră în limită. Măsurat: un PDF scanat de 13,6 MB → 564 KB.

Extensia din `file.name` urmează întotdeauna conținutul real: un `.jpg` convertit la PDF e livrat ca
`.pdf`, nu cu numele original.

Două excepții, ambele intenționate:

- **PDF-urile cu text nativ nu se rasterizează.** Rasterizarea ar distruge ireversibil textul
  căutabil, deci un contract PDF nativ peste limită se livrează ca atare (peste 1,6 MB) în loc să
  ajungă un teanc de poze. Preferăm un fișier pe care îl puteți refuza vizibil unuia degradat.
- **PDF-urile de peste 40 de pagini nu se rasterizează.** Operația durează ~1,2 s/pagină și rulează
  în timp ce așteptați răspunsul; peste acest prag ar depăși limita de timp a serverului.

Dacă fișierul rămâne peste prag, se livrează oricum, cu avertisment în jurnalul Cargo360 — un refuz
din partea CTS e vizibil în `update_documents` și intră în statistică, pe când un document nelivrat
ar dispărea tăcut.

**Fișierele inutilizabile nu se livrează deloc.** Dacă pregătirea eșuează și ar rezulta un fișier gol,
sau un format greșit pe o categorie care cere PDF, documentul e raportat ca lipsă (`file: null`,
id-ul în `missing_files`) și **nu** e marcat ca trimis. Un document lipsă se poate recupera; unul gol
„confirmat livrat" ar rămâne pentru totdeauna un succes fals în statistică.

**Notă:** câmpul `original_attachment` (prezent doar când un PDF a fost spart în mai multe documente)
conține fișierul-sursă integral, **fără** aceste limite — e material de referință, nu documentul care
se atașează pe entitate.

---

## Contract

```
POST http://95.216.144.102:8501/api/v1/cts/update_documents
Header: X-CTS-Token: <cheia>
Content-Type: application/json
```

Cheia documentului este **`attachment_id`** — exact valoarea `id_mailguard` livrată în feed
(`GET /cts/get_email_documents` → `documents[].attachment_id`, și `attachments[].id_mailguard` în `get_emails`).

Trei liste, toate opționale, combinabile în același apel:

| Listă | Când se trimite | Efect |
|---|---|---|
| `saved` | documentul a fost atașat pe o entitate CTS | marchează succesul asocierii |
| `failed` | documentul nu a putut fi procesat | marchează eșecul + motivul |
| `deleted` | lotul zilnic: documente șterse de operatori | marchează ștergerea ulterioară |

### Câmpuri

| Câmp | Tip | Obligatoriu | Note |
|---|---|---|---|
| `attachment_id` | int | da | acceptă și `"34941"` sau `"#34941"` |
| `part_no` | int | recomandat | **vezi mai jos** — identifică UN document dintr-un fișier cu mai multe acte |
| `extraction_id` | int | alternativă la `part_no` | id-ul unic al documentului, livrat în feed |
| `entity_type` | string | la `saved` | `contract` \| `driver` \| `vehicle` |
| `entity_id` | int | la `saved` | id-ul entității din CTS |
| `reason` | string | la `failed` | motivul respingerii (max 2000 caractere) |
| `admin_id` | int \| null | opțional la `deleted` | cine a șters |
| `deleted_at` | string | la `deleted` | **ISO 8601 cu oră**, ex. `2026-08-12T03:00:00Z` |

La `deleted`, câmpurile `entity_type` / `entity_id` sunt **acceptate dar ignorate** — starea entității
a fost deja înregistrată la confirmarea de salvare. Le puteți trimite (nu strică), dar nu e nevoie.

### Identificarea documentului: `part_no` sau `extraction_id`

Un fișier PDF poate conține mai multe acte (contract + talon + act de identitate), fiecare devenind
un document separat, **toate cu același `attachment_id`**. Măsurat pe date reale: din 226 de
atașamente, 47 conțineau mai multe documente, unele amestecând categoriile.

De aceea, o confirmare care trimite **doar** `attachment_id` se aplică **tuturor** actelor din fișier.
Asta e corect doar când fișierul conține un singur document. Altfel, un act de identitate ar fi
înregistrat ca atașat pe același vehicul ca talonul — o asociere care nu s-a întâmplat.

Trimiteți `part_no` (sau `extraction_id`, ambele livrate în feed) ca să confirmați exact documentul
procesat. Ambele identifică același lucru; folosiți-l pe cel mai comod.

---

## Exemple

### Confirmarea procesării unui email (imediat după `get_email_documents`)

```bash
curl -X POST "http://95.216.144.102:8501/api/v1/cts/update_documents" \
  -H "X-CTS-Token: <CHEIA>" \
  -H "Content-Type: application/json" \
  -d '{
    "saved": [
      {"attachment_id": 34941, "part_no": 0, "entity_type": "vehicle", "entity_id": 8821},
      {"attachment_id": 34941, "part_no": 1, "entity_type": "driver",  "entity_id": 512}
    ],
    "failed": [
      {"attachment_id": 34942, "part_no": 0,
       "reason": "categorie netratata: document_type_id lipsa"}
    ]
  }'
```

### Lotul zilnic de ștergeri (comanda `check:mail-guard-deleted-documents`, 04:00 UTC)

```bash
curl -X POST "http://95.216.144.102:8501/api/v1/cts/update_documents" \
  -H "X-CTS-Token: <CHEIA>" \
  -H "Content-Type: application/json" \
  -d '{
    "deleted": [
      {"attachment_id": 34941,
       "part_no": 0,
       "admin_id": 17,
       "deleted_at": "2026-08-12T03:00:00Z"}
    ]
  }'
```

### Răspuns (identic ca structură pentru orice combinație de liste)

```jsonc
{
  // CONFIRMĂRI aplicate (câte intrări din payload au avut efect)
  "marked_saved": 2,
  "marked_failed": 1,
  "marked_deleted": 0,
  // RÂNDURI atinse — diferă de cele de sus doar când o confirmare fără `part_no`
  // acoperă mai multe acte din același fișier
  "rows_saved": 2,
  "rows_failed": 1,
  "rows_deleted": 0,
  "partially_deleted": 0, // ștergere aplicată doar unei părți din actele fișierului
  "unknown": 0,           // nu există niciun document cu acest identificator
  "already_final": 0,     // documentul există, dar e deja marcat șters (stare finală)
  "not_saved_yet": 0,     // documentul există, dar încă nu a plecat spre CTS
  "orphan_deleted": 0,    // ștergere pentru un document fără istoric local
  "already_deleted": 0,   // ștergere repetată (deja marcat șters)
  "invalid": 0,           // attachment_id neinterpretabil ca număr
  "bad_timestamp": 0      // deleted_at neparsabil → s-a folosit ora curentă
}
```

HTTP 200 la orice lot procesabil. HTTP 400 dacă payload-ul e gol sau o listă nu e listă.
HTTP 413 dacă lotul depășește **5.000 de documente** per apel — împărțiți-l. (Peste ~50.000 procesarea
ar depăși timpul maxim de răspuns și tot lotul s-ar pierde, inclusiv confirmările valide; refuzul
explicit e preferabil.)
HTTP 422 dacă corpul cererii nu e un obiect JSON (ex. un array sau un șir la rădăcină).
HTTP 401 la token lipsă/greșit.

---

## Comportament

**Idempotent** în efect, nu în contoare. Retrimiterea aceluiași lot nu schimbă nimic în date și nu
dublează nimic. Dar atenție la interpretare, dacă vă construiți verificări automate peste răspuns:

- `saved` și `failed` **re-raportează aceleași cifre** la fiecare apel identic. Un document deja
  `saved` reconfirmat ca `saved` iese tot în `marked_saved`. Nu există contor `already_saved`.
- Doar `deleted` are stare finală: a doua ștergere a aceluiași document iese în `already_deleted`,
  iar `marked_deleted` scade la 0.

Deci **nu** folosiți „`marked_saved` scade la 0 la reîncercare" ca semnal — nu se întâmplă.

**Un id necunoscut nu produce eroare.** Restul lotului se procesează normal; un lot de 200 de
confirmări nu se pierde din cauza unei intrări greșite. Cele trei situații sunt numărate separat:

| Contor | Înseamnă |
|---|---|
| `unknown` | nu există niciun document cu acest identificator (curățat, sau id greșit) |
| `already_final` | documentul există, dar e deja marcat șters — nu se mai poate schimba |
| `not_saved_yet` | documentul există, dar încă nu a plecat spre CTS (e în validare) |

`not_saved_yet` la o confirmare de salvare e un semnal util: înseamnă că ați confirmat un document
pe care nu vi l-am trimis încă. Cel mai probabil ați trimis confirmarea fără `part_no`, pentru un
fișier din care doar o parte din acte au fost livrate.

**Ștergerea se aplică DOAR peste un document confirmat salvat.** Dacă CTS anunță ștergerea unui document
pentru care Cargo360 nu a primit niciodată confirmarea de salvare, ștergerea e numărată în `not_saved_yet`
și **nu** se deduce că documentul fusese salvat. Motivul: o deducere ar umfla artificial rata de succes a
asocierii automate — exact indicatorul pentru care s-a cerut epicul.

**Precedență la conflict.** Dacă același `attachment_id` apare în mai multe liste în același apel, câștigă
starea cea mai avansată (`deleted` > `failed` > `saved`) și documentul e numărat o singură dată. Duplicatele
din aceeași listă sunt deduplicate (ultima apariție câștigă).

**Data trebuie să fie ISO 8601.** Un format ambiguu precum `12/08/2026` ar fi interpretat greșit (luna
înaintea zilei, deci 8 decembrie în loc de 12 august), așa că e respins: se folosește ora curentă și se
raportează în `bad_timestamp`. O dată greșită tăcut e mai dăunătoare decât una respinsă vizibil.

**Documentele respinse pot fi corectate și retrimise.** După un `failed`, dacă operatorul corectează
documentul în Cargo360, acesta redevine disponibil la următorul `get_email_documents` și o confirmare
ulterioară îl trece pe `saved`. Statistica reflectă starea finală, nu prima încercare.

**Un atașament poate conține mai multe documente** (vezi secțiunea despre `part_no`). O confirmare
fără `part_no` / `extraction_id` se aplică **tuturor** actelor din fișier și e numărată ca o singură
confirmare (`marked_saved: 1`), dar atinge mai multe rânduri (`rows_saved: 3`). Trimiteți
identificatorul documentului ca statistica să reflecte realitatea per act.

**Confirmarea se aplică doar documentelor chiar livrate.** Actele dintr-un fișier care sunt încă în
validare (nelivrate) nu sunt atinse de o confirmare, chiar dacă împart `attachment_id`-ul — altfel ar
fi înregistrate ca salvate fără să fi fost trimise vreodată, și nu v-ar mai fi livrate niciodată.

---

## Ciclul de viață al unui document

```
extras  ──►  trimis spre CTS  ──►  salvat pe entitate  ──►  șters de operator
   │               │                      │
   │               │                      └── failed (respins de CTS; corectabil, revine la „trimis")
   │               └── rămâne „în așteptare" cât timp CTS nu confirmă
   └── nu a plecat niciodată (extragere eșuată / necesită validare manuală)
```

Stările interne corespunzătoare: `extracted` → `sent` → `saved` | `failed` ; `saved` → `deleted`.

---

## Statistica rezultată

`GET /api/v1/cts/document-stats` (autentificare de administrator, nu token CTS) întoarce pâlnia pe categorii.
Aceleași cifre apar pe pagina **Procesare documente**.

Fiecare procent are alt numitor — de aceea sunt numite explicit în răspuns:

| Indicator | Formulă | Răspunde la întrebarea |
|---|---|---|
| `sent_pct` | trimise / extrase | câte documente extrase apucă să plece spre CTS |
| `saved_pct` | `ever_saved` / trimise | din cele plecate, câte s-au atașat pe entitate |
| `deleted_pct` | șterse / `ever_saved` | din cele ajunse pe entitate, câte au fost șterse |

`ever_saved = saved + deleted_after`: un document șters a fost, prin definiție, salvat înainte. Fără această
corecție, o ștergere ar scădea și rata de succes a asocierii, deși asocierea chiar reușise.

---

## Note de implementare (Cargo360)

Datele stau în tabela `cts_document_tracking`, **fără chei străine** către `attachments`,
`document_extractions` sau `emails`. E intenționat: `scripts/storage_cleanup.sh` șterge zilnic
extracțiile procesate din zilele anterioare, iar CTS raportează ștergerile cu o zi întârziere. Cu chei
străine, statistica ar dispărea odată cu documentul. Se păstrează doar numele, categoria și starea —
niciodată fișierul.

Cheia unică e `(attachment_id, part_no)`, simetric cu `document_extractions`, tocmai pentru cazul
atașamentului cu mai multe acte.

Rândul se creează la **extragere** (stare `extracted`), nu la trimitere — altfel numitorul „câte s-au
extras în total" ar fi trebuit citit din tabela golită zilnic, iar procentele s-ar fi resetat în fiecare noapte.

Migrații: `20260812_cts_document_tracking.sql`, `20260812b_cts_tracking_part_no.sql`.

---

## De implementat pe partea CTS

1. La finalul procesării documentelor unui email (`check:client-contact-email-get-mail-guard-documents`),
   apel `POST /cts/update_documents` cu `saved` (documentele atașate pe entitate, cu `entity_type` +
   `entity_id`) și `failed` (cele excluse din procesare sau eșuate, cu `reason`).
2. **Includeți `part_no` (sau `extraction_id`) în fiecare intrare.** Ambele vin în feed, per document.
   Fără ele, confirmarea se aplică tuturor actelor din același fișier — vezi secțiunea dedicată.
3. Rețineți `part_no`/`extraction_id` alături de `mailguard_id` pe documentul din CTS, ca lotul zilnic
   de ștergeri să le poată trimite înapoi.
4. Comandă zilnică nouă (`check:mail-guard-deleted-documents`, 04:00 UTC) care interoghează tabelele de
   documente pentru rânduri cu `mailguard_id` completat și `deleted_at` în ziua precedentă, și trimite
   lista în `deleted`.
5. `deleted_at` se trimite în **UTC, ISO 8601, cu oră** (o dată fără oră e respinsă).
6. Nu vă bazați pe „`marked_saved` scade la reîncercare" — vezi secțiunea *Comportament*.
