-- Backfill legături mesaj<->client din sursele autoritative.
--
-- Context (măsurat pe staging, 2026-07-29, v0.46.59):
--   emails: 8.437 total, 4.918 fără client_id
--   calls:  16.862 total, 10.935 fără client_id
-- Sursa autoritativă a legăturii e CTS (raw->...->client_id = clients.iris_client_id),
-- populată 100% pe rândurile CTS existente. Matching-ul local pe adresă/telefon rămâne
-- fallback pentru mesajele fără corespondent CTS.
--
-- Toate pașii: aditivi (doar WHERE client_id IS NULL), idempotenți, re-rulabili.
-- Ordinea contează: pasul 1 depinde de client_phone_keys din 20260729_phone_client_match_index.sql.

-- ── Pas 1: apeluri ← CTS (sursa autoritativă) ────────────────────────────────
UPDATE calls c
SET client_id = cl.id, updated_at = NOW()
FROM cts_calls_ground_truth gt
JOIN clients cl ON cl.iris_client_id = (gt.raw->>'client_id')::bigint
WHERE gt.call_local_id = c.id
  AND c.client_id IS NULL
  AND gt.raw->>'client_id' ~ '^[0-9]+$';

-- ── Pas 2: emailuri ← CTS (sursa autoritativă) ───────────────────────────────
UPDATE emails e
SET client_id = cl.id, updated_at = NOW()
FROM cts_ground_truth gt
JOIN clients cl ON cl.iris_client_id = (gt.raw->'extra'->>'client_id')::bigint
WHERE gt.email_id = e.id
  AND e.client_id IS NULL
  AND gt.raw->'extra'->>'client_id' ~ '^[0-9]+$';

-- ── Pas 3: apeluri ← telefon (fallback, doar potriviri UNICE) ────────────────
-- Numerele CargoTrack (037443006x) sunt capătul nostru, nu al clientului: dacă un număr
-- se mapează pe mai mulți clienți, NU se atribuie (mai bine NULL decât greșit într-un
-- calcul de satisfacție).
WITH cand AS (
    SELECT c.id AS call_id, min(k.client_id) AS client_id, count(DISTINCT k.client_id) AS n
    FROM calls c
    JOIN client_phone_keys k
      ON k.phone_key = right(regexp_replace(coalesce(c.caller_number, ''), '\D', '', 'g'), 9)
      OR k.phone_key = right(regexp_replace(coalesce(c.callee_number, ''), '\D', '', 'g'), 9)
    JOIN clients cl ON cl.id = k.client_id AND cl.is_active = TRUE
    WHERE c.client_id IS NULL
    GROUP BY c.id
)
UPDATE calls c
SET client_id = cand.client_id, updated_at = NOW()
FROM cand
WHERE c.id = cand.call_id AND cand.n = 1 AND c.client_id IS NULL;

-- ── Pas 4: emailuri TRIMISE ← destinatar (fallback) ──────────────────────────
-- Pe emailurile trimise de noi expeditorul e o adresă CargoTrack, deci clientul e
-- destinatarul. Adresele interne se exclud. Doar potriviri unice.
WITH cand AS (
    SELECT e.id AS email_id, min(cl.id) AS client_id, count(DISTINCT cl.id) AS n
    FROM emails e
    CROSS JOIN LATERAL jsonb_array_elements_text(
        coalesce(e.to_addresses, '[]'::jsonb) || coalesce(e.cc_addresses, '[]'::jsonb)
    ) AS t(addr)
    JOIN clients cl ON cl.emails @> to_jsonb(lower(trim(t.addr))) AND cl.is_active = TRUE
    WHERE e.client_id IS NULL
      AND lower(trim(t.addr)) NOT LIKE '%cargotrack.ro'
    GROUP BY e.id
)
UPDATE emails e
SET client_id = cand.client_id, updated_at = NOW()
FROM cand
WHERE e.id = cand.email_id AND cand.n = 1 AND e.client_id IS NULL;
