-- Adrese de email care identifică UNIC un client — folosite la legarea mailurilor orfane
-- în calculul de satisfacție.
--
-- Problema (staging, 2026-07-29): `satisfaction_engine._fetch_month_interactions` lega mailurile
-- fără `client_id` prin DOMENIUL expeditorului. Dar 171 de domenii sunt partajate între 646 de
-- clienți (ex. `ruptela.com` la 8 clienți, unul cu 0 mailuri proprii), deci fiecare primea
-- mailurile tuturor celorlalți — de unde rapoarte de tip „am analizat 54 de interacțiuni" pentru
-- un client care are 10 în total.
--
-- Nici adresa exactă nu e suficientă singură: în CTS multe adrese sunt puse pe mai mulți clienți
-- — furnizori (`support@ruptela.com` la 8), bănci (`no-reply@unicredit.ro` la 6,
-- `tiberiu.fenesi@btleasing.ro` la 5), sau text liber în loc de adresă (`dispecer` la 37,
-- `sotia` la 27, `sofer` la 17). O adresă partajată nu identifică pe nimeni.
--
-- Tabela ține doar adresele care apar la EXACT un client activ. Calculul echivalent la runtime
-- costa ~380 ms per client (agregare peste 16k clienți) — inacceptabil pentru un lot de 300.
-- Se reconstruiește după sync-ul de clienți (`iris_sync` → `rebuild_client_unique_emails`).

-- `email` e TEXT, nu VARCHAR(320): unele intrari din CTS nu sunt adrese, ci liste intregi
-- lipite intr-un singur element jsonb (peste 320 caractere). Le filtram mai jos pe lungime,
-- dar tipul trebuie sa le tolereze la INSERT.
CREATE TABLE IF NOT EXISTS client_unique_emails (
    client_id  BIGINT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    email      TEXT NOT NULL,
    PRIMARY KEY (client_id, email)
);

CREATE INDEX IF NOT EXISTS idx_client_unique_emails_email ON client_unique_emails(email);

-- Populare (idempotent).
INSERT INTO client_unique_emails (client_id, email)
WITH parts AS (
    SELECT c.id AS client_id, lower(trim(part)) AS addr
    FROM clients c,
         jsonb_array_elements_text(c.emails) e,
         unnest(string_to_array(e, ';')) AS part
    WHERE c.is_active
),
counted AS (
    SELECT addr, count(DISTINCT client_id) AS n FROM parts GROUP BY 1
)
SELECT p.client_id, p.addr
FROM parts p JOIN counted k ON k.addr = p.addr
WHERE k.n = 1
  AND p.addr LIKE '%@%'
  AND length(p.addr) <= 320          -- exclude intrarile care sunt liste, nu adrese
  AND p.addr NOT LIKE '% %'          -- o adresa nu contine spatii
  AND p.addr NOT LIKE '%cargotrack.ro'
  AND p.addr NOT LIKE '%trakosoft.ro'
ON CONFLICT DO NOTHING;

DO $$
DECLARE n INT; c INT;
BEGIN
    SELECT count(*), count(DISTINCT client_id) INTO n, c FROM client_unique_emails;
    RAISE NOTICE 'client_unique_emails: % adrese unice pentru % clienti', n, c;
END $$;
