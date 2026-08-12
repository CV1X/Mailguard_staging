-- Fix: excepție absolută PPHU/PPCB/PPBG/ASCF → suport_1 în promptul taxe_drum
-- Problema: regula era scrisă doar pt OP-uri; facturi proformă cu HU-GO în context mergeau eronat la taxe_drum
-- Ex: "Factură proformă încărcare cont HU-GO" cu PPHU44770 → taxe_drum (greșit) → suport_1 (corect)
UPDATE ai_department_prompts
SET
    prompt_text = REPLACE(
        prompt_text,
        'EXCEPTIE: OP-uri cu seria PPCB, PPBG, PPHU sau ASCF merg la suport_1',
        'EXCEPTIE ABSOLUTA (orice tip de document — OP, factura proforma, factura fiscala, chitanta, email scurt): daca mesajul sau subiectul contine seria PPHU, PPCB, PPBG sau ASCF (ex. PPHU44770, PPCB001, PPBG-123) -> suport_1, NU taxe_drum, chiar daca contextul e HU-GO sau toll'
    ),
    updated_at = NOW()
WHERE department = 'taxe_drum'
  AND prompt_text LIKE '%EXCEPTIE: OP-uri cu seria PPCB%';

-- Idempotenta: daca staging-ul a rulat deja, WHERE nu mai prinde nimic (string vechi absent) -> 0 rows affected, OK.
