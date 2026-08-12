-- Seed the IRIS prompt used to turn a backup diff into a human worklog summary.
-- Idempotent. The actual LLM endpoint/key are provided separately (env NOVA_LLM_URL/IRIS_LLM_KEY).
-- Run: sudo docker exec -i <db_container> psql -U mailguard -d mailguard < this_file.sql
INSERT INTO prompts (code, name, description, system_prompt, user_prompt_template, model, temperature, max_tokens, created_by)
VALUES (
  'backup_worklog',
  'Rezumat worklog backup',
  'Transformă diferențele de cod dintre două backup-uri într-un rezumat uman (bullet points), pentru pagina Setări > Backup-uri.',
  'Ești un asistent care rezumă pe înțelesul oamenilor modificările aduse codului unei aplicații între două backup-uri. Primești lista fișierelor modificate și un diff tehnic. Produ un rezumat SCURT în limba română, ca listă de bullet points, descriind CE funcționalități/feature-uri s-au adăugat sau schimbat și de ce contează pentru utilizator. NU include linii de cod, nume de fișiere/variabile sau detalii de implementare. Maxim 6 bullet-uri, fiecare o propoziție clară.',
  'Fișiere modificate: {{FILES}}' || chr(10) || chr(10) || 'Diff tehnic (doar referință internă, NU îl cita):' || chr(10) || '{{DIFF}}' || chr(10) || chr(10) || 'Scrie rezumatul în bullet points, limbaj uman:',
  'gemma',
  0.20,
  400,
  'claude-cc'
)
ON CONFLICT (code) DO NOTHING;
