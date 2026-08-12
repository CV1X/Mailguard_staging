# Mesaj însoțitor pentru Razvan

Salut Razvan,

Pornim modulul „Task-uri" în Cargo360 (până acum doar placeholder) — task-urile vin exclusiv din
CTS, la fel cum am făcut deja cu mailurile (`/cts/ground-truth`) și apelurile (`/cts/calls`).

Am pregătit specificația completă a endpoint-ului de care avem nevoie — vezi
`OUTBOX_tasks_endpoint.md` atașat: `GET /cts/tasks` pe același Gateway, aceeași cheie
`X-Mailguard-Key` (fără secret nou), polling incremental pe `since`/`updated_at`, exact pattern-ul
deja validat.

Am nevoie în special de răspuns la întrebările din secțiunea 9 (tipuri de task, statusuri terminale,
legătura cu mail/apel, format `operator_asignat`, volum estimat) ca să pot dimensiona corect
procesarea pe partea mea.

Notă separată: pentru angajați asignați pe task-uri care nu sunt încă importați în Cargo360 (dept
în afara listei noastre curente), NU am nevoie de nimic nou de la tine — `/cts/employees` are deja
tot ce trebuie; e o ajustare doar pe partea mea de filtrare.

Mersi!
