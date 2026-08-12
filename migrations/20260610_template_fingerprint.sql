-- 20260610_template_fingerprint.sql
-- FAZA 3 — Learning la decarantinare scoped pe TEMPLATE FINGERPRINT.
--
-- Scop: cand un om marcheaza un email ca NOT phishing, suprimarea automata sa se aplice
-- DOAR mailului NEAR-IDENTICAL (acelasi template) de la acelasi expeditor, nu oricarui mail
-- de la acel sender/domeniu. Reduce riscul ca un singur mail benign sa deschida poarta pentru
-- tot ce trimite acel expeditor (sender legit compromis / phisher care a trimis candva benign).
--
-- Compatibilitate: regulile existente (scope_type='sender_exact'|'domain', template_fingerprint NULL)
-- se comporta EXACT ca azi. Amprenta e o legare OPTIONALA, aditiva.
--
-- Fingerprint = SimHash 64-bit peste continutul NOU normalizat (app/services/template_fingerprint.py),
-- stocat ca HEX TEXT (SimHash e unsigned 64-bit, depaseste BIGINT signed). Match = distanta Hamming <= k.

ALTER TABLE suppression_rules
  ADD COLUMN IF NOT EXISTS template_fingerprint TEXT,          -- hex SimHash64 al exemplarului aprobat; NULL = regula legacy sender/domain
  ADD COLUMN IF NOT EXISTS fingerprint_k SMALLINT DEFAULT 3;   -- distanta Hamming maxima pentru "acelasi template"

-- scope_type poate fi acum si 'template' (sender_exact + legare de fingerprint).
-- (Nu adaugam constrangere CHECK noua ca sa nu rupem randurile existente.)

-- Golden-set: amprente de template KNOWN-BAD care NU pot fi suprimate automat niciodata
-- (peste NEVER_SUPPRESS care deja protejeaza codurile de malware). Daca un mail face match
-- pe un golden-bad, ramane in carantina indiferent de suppression_rules.
CREATE TABLE IF NOT EXISTS golden_bad_templates (
  id              BIGSERIAL PRIMARY KEY,
  fingerprint     TEXT NOT NULL,                 -- hex SimHash64
  k               SMALLINT NOT NULL DEFAULT 3,
  label           VARCHAR(200),
  sample_email_id BIGINT REFERENCES emails(id) ON DELETE SET NULL,
  created_by      VARCHAR(100),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_golden_bad_fp ON golden_bad_templates(fingerprint);

-- Rollback (manual, daca e nevoie):
--   ALTER TABLE suppression_rules DROP COLUMN IF EXISTS template_fingerprint;
--   ALTER TABLE suppression_rules DROP COLUMN IF EXISTS fingerprint_k;
--   DROP TABLE IF EXISTS golden_bad_templates;
