# CTS → Cargo360 — bifa „Trimite mail automat" (răspuns automat la soluționare)

**Status:** implementat în Cargo360. **Necesită adăugarea bifei + a câmpului în CTS** (partea voastră — vezi secțiunile „Ce trebuie făcut în CTS" și „Câmpul în payload").
**Versiune:** 2026-06-30.

## Pe scurt (pentru product owner)

Când o sesizare este **soluționată** în CTS, Cargo360 poate trimite automat clientului un mesaj
scurt și generic de confirmare („solicitarea dumneavoastră a fost soluționată de un coleg din echipa
noastră"), ca să nu mai scrie operatorul boilerplate-ul de închidere.

Vrem ca **operatorul din CTS să decidă** dacă Cargo360 trimite acest mesaj sau nu — printr-o **bifă
per sesizare**, „**Trimite mail automat**", **bifată implicit (TRUE)**. Dacă operatorul preferă să
răspundă el (alege un template / scrie manual), **debifează** → Cargo360 **NU** trimite (răspunde omul).

## Ce trebuie făcut în CTS

1. **Bifă per sesizare/email:** „Trimite mail automat (la soluționare)". **Default: bifată (TRUE).**
2. La **debifare** — sau când operatorul **selectează un template / răspunde manual** — valoarea devine **FALSE**.
3. **Transmiteți valoarea către Cargo360** în înregistrarea sesizării, prin **același feed de sync prin
   care Cargo360 primește deja statusul (`solved`), reply-ul, data soluționării etc.** Este un câmp
   boolean nou pe înregistrare; restul payload-ului rămâne neschimbat.

## Câmpul în payload

- **Nume recomandat (canonic):** `solved_auto_reply`
- **Tip:** boolean. **Default:** `true`.
- Cargo360 îl caută **top-level** pe înregistrare; dacă aveți deja altă convenție, acceptăm tolerant și
  alias-urile: `auto_reply`, `send_auto_reply`, `auto_reply_on_solved`, `auto_send`, `trimite_auto`,
  `send_solved_auto` (top-level sau în obiectul `extra`).
- **Valori acceptate:** `true` / `false` (recomandat); sau `1` / `0`, `"true"` / `"false"`,
  `"yes"` / `"no"`, `"da"` / `"nu"`, `"on"` / `"off"`. Lipsă / necunoscut → tratat ca „nestabilit" (vezi mai jos).

Exemplu de înregistrare în feed (doar câmpul nou e adăugat):
```jsonc
{
  "email_id": 39581,            // sau "message_id"
  "status": "solved",
  "solved_auto_reply": true,    // <— NOU: bifa operatorului. false = a răspuns manual, Cargo360 NU trimite
  // ... reply_text, solved_at, atașamente etc. — neschimbate ...
}
```

## Ce face Cargo360 cu valoarea

La trecerea sesizării în **`solved`**:

| `solved_auto_reply` | Comportament Cargo360 |
|---|---|
| `true`  | Eligibil → generează și trimite **un singur** mesaj scurt de închidere. |
| `false` | **NU trimite** (operatorul a răspuns manual). |
| lipsă / `null` | Momentan tratat ca eligibil (ca să putem valida pe trafic real); **recomandăm să trimiteți mereu valoarea explicită**. |

### Garanții anti-duplicat / anti-spam (gestionate de Cargo360 — NU trebuie tratate de voi)

- **Maxim 1 mail automat per adresă de expeditor la fiecare 10 minute.** Dacă 10 sesizări către aceeași
  adresă se închid simultan, pleacă **un singur** mail; restul sunt sărite. (Cea mai veche câștigă.)
- **O singură decizie per email** la închidere — idempotent, nu trimite de două ori pentru aceeași soluționare.
- Trimite **doar la prima tranziție** în `solved`; re-sync-urile ulterioare și sesizările istorice **nu** retrimit.
- Trimite doar dacă mesajul generat are **încredere suficientă** (prag intern); altfel rămâne nesemnalat.
- **Nu** răspunde expeditorilor automați / interni sau mesajelor de tip spam.

## Note

- Mesajul de închidere este **generic**, fără identificatori (nr. înmatriculare, factură, contract, sume,
  nume) și conștient de tipul cererii (plată / documente / sesizare).
- Câmpul e **backward-compatible**: până când CTS îl trimite, Cargo360 tratează absența ca „nestabilit"
  — nu strică nimic în fluxul actual.
- Activarea trimiterii efective este etapizată pe partea Cargo360; **contractul de mai sus (bifa +
  câmpul `solved_auto_reply`) este tot ce trebuie implementat în CTS.**
