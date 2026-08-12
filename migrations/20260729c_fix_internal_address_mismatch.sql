-- Fix: adresele INTERNE CargoTrack din clients.emails produceau atribuiri arbitrare de client.
--
-- Constatare (staging, 2026-07-29): 71 clienți aveau în `clients.emails` 193 adrese din
-- domeniul nostru — `office@cargotrack.ro` la 26 de clienți, adrese de angajați
-- (`calin.lucaciu@`, `nicoleta.berde@`, …) la 3-8 clienți fiecare, plus placeholder-e
-- `fara_email@cargotrack.ro` la 9. În CTS ele înseamnă „agentul care se ocupă de client",
-- NU „adresa clientului".
--
-- Efect: `match_client()` face `emails @> [from_address] LIMIT 1`, deci orice email trimis de
-- un coleg era atribuit unui client ales arbitrar dintre cei 26 care „au" office@. 44 de
-- emailuri au primit client greșit din backfill-ul 20260729b (pasul 4) + 321 dinainte.
--
-- Soluție: adresele interne NU se folosesc niciodată la matching. Le mutăm din `clients.emails`
-- într-o coloană separată, ca informația să nu se piardă (rămâne vizibilă ca date de contact).
-- Codul (`process_email._is_internal_address`) refuză în plus adresele interne la matching.
--
-- Idempotent: re-rularea nu mai găsește adrese interne de mutat.

-- ── 1. Păstrăm adresele interne separat, nu le pierdem ───────────────────────
ALTER TABLE clients ADD COLUMN IF NOT EXISTS internal_contact_emails JSONB NOT NULL DEFAULT '[]'::jsonb;

COMMENT ON COLUMN clients.internal_contact_emails IS
  'Adrese CargoTrack asociate clientului în CTS (agentul care îl gestionează, placeholder-e). '
  'Informative — NU se folosesc la matching email↔client.';

UPDATE clients c
SET internal_contact_emails = (
        SELECT jsonb_agg(DISTINCT lower(e))
        FROM jsonb_array_elements_text(c.emails) e
        WHERE lower(e) LIKE '%cargotrack.ro'
    ),
    emails = coalesce((
        SELECT jsonb_agg(e)
        FROM jsonb_array_elements_text(c.emails) e
        WHERE lower(e) NOT LIKE '%cargotrack.ro'
    ), '[]'::jsonb),
    updated_at = NOW()
WHERE EXISTS (
    SELECT 1 FROM jsonb_array_elements_text(c.emails) e
    WHERE lower(e) LIKE '%cargotrack.ro'
);

-- ── 2. Anulăm atribuirile făcute pe baza unei adrese interne ─────────────────
-- Doar cele care NU sunt confirmate de CTS: dacă CTS spune explicit clientul, are dreptate
-- (un client poate coresponda legitim prin adresa colegului care îl gestionează).
UPDATE emails e
SET client_id = NULL, updated_at = NOW()
WHERE e.client_id IS NOT NULL
  AND lower(e.from_address) LIKE '%cargotrack.ro'
  AND NOT EXISTS (
      SELECT 1 FROM cts_ground_truth gt
      WHERE gt.email_id = e.id
        AND gt.raw->'extra'->>'client_id' ~ '^[0-9]+$'
  );
