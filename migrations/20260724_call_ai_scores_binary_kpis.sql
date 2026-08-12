-- v0.44.7: coloane KPI binar pentru prompturi noi de scoring apeluri
ALTER TABLE call_ai_scores
  ADD COLUMN IF NOT EXISTS agentul_sa_prezentat        boolean,
  ADD COLUMN IF NOT EXISTS clientul_aminta_judecata    boolean,
  ADD COLUMN IF NOT EXISTS clientul_aminta_renuntare   boolean,
  ADD COLUMN IF NOT EXISTS clientul_contactat_anterior boolean;
