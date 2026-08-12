-- Exclude din satisfacție entitățile care NU sunt clienți: sisteme automate, furnizori,
-- pseudo-clienți administrativi.
--
-- Constatare la rularea pe eșantionul de 300 (2026-07-29): din 38 de clienți „nesatisfăcuți",
-- primele două poziții erau `HU-GO TEMP` (8,5%, 131 interacțiuni) și
-- `HU-GO ELECTRONIC TOLL SYSTEM` (12,8%, 258) — sisteme de taxare rutieră din Ungaria care trimit
-- exclusiv notificări automate (înregistrări vehicule, blacklist NÚSZ/hu-go.hu). Motorul le
-- interpreta ca reclamații ale unui client nemulțumit. IRIS chiar semnala în raționament că
-- „NU sunt interacțiuni reale cu serviciul CARGO TRACK", dar scorul rămânea mic și le raporta
-- ca clienți nesatisfăcuți — poluând lista pe care echipa o folosește pentru intervenții.
--
-- Mecanismul `clients.satisfaction_exclude` exista deja și era folosit corect pentru
-- CARGO TRACK SOLUTIONS SRL, RUPTELA UAB și UNKNOWN CLIENT. Migrația îl extinde la restul
-- entităților de același fel, identificate pe nume.
--
-- Idempotent: doar `WHERE NOT satisfaction_exclude`. Reversibil: `satisfaction_exclude = false`.

UPDATE clients SET satisfaction_exclude = TRUE, updated_at = NOW()
WHERE NOT satisfaction_exclude
  AND (
       name ILIKE 'HU-GO%'              -- sisteme de taxare rutieră Ungaria (NÚSZ / hu-go.hu)
    OR name ILIKE '%NOTIFICATION SYSTEM%'  -- pseudo-client pentru notificări automate
    OR name ILIKE 'PARTENERI CLIENTI%'     -- grupare administrativă, nu o firmă
    OR name ILIKE 'RUPTELA%'               -- furnizor de dispozitive (RUPTELA UAB deja exclus)
    OR name ILIKE 'CARGOFUEL%'             -- aplicație internă CargoTrack
    OR name ILIKE 'EXPERT SOFTWARE GROUP%' -- furnizor software
  );

DO $$
DECLARE n INT;
BEGIN
    SELECT count(*) INTO n FROM clients WHERE satisfaction_exclude;
    RAISE NOTICE 'clienti exclusi din satisfactie: %', n;
END $$;
