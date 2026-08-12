-- Mailuri automate marcate SOLVED spre CTS (feed: campul `mark_as_solved`).
-- Aditiv + idempotent (re-rulabil fara efect). Schema ajunge pe prod DOAR prin acest fisier.

-- Flag persistat: mailul a plecat efectiv spre CTS marcat ca solved (setat la ack/update_emails).
ALTER TABLE emails ADD COLUMN IF NOT EXISTS cts_mark_solved BOOLEAN NOT NULL DEFAULT FALSE;

-- Reguli deterministe (expeditor + substring subiect). Editabile din DB FARA deploy.
-- Format: lista de {senders:[...], subject_contains:[...]}. subject_contains gol => orice subiect.
-- [] (lista goala) = kill-switch (dezactivat). Oglindeste _DEFAULT_RULES din cts_auto_solved.py.
INSERT INTO settings(key, value) VALUES ('cts.auto_solved_rules', '[
  {"senders":["noreply@itsbulgaria.com"],"subject_contains":["Daily summary for toll products for"]},
  {"senders":["secretariat@urbansiasociatii.ro"],"subject_contains":["Inregistrare: Dosar CARGO TRACK SOLUTIONS SRL"]},
  {"senders":["noreply@hu-go.hu"],"subject_contains":["Vélelmezett jogosulatlan úthasználat miatti riasztás"]},
  {"senders":["support@expert-erp.net"],"subject_contains":[]},
  {"senders":["notificari@euplatesc.ro","mis.batch@btrl.ro","notificari@europayment.services"],"subject_contains":["Tranzactii zilnice","Tranzactii ecomm"]}
]'::jsonb)
ON CONFLICT (key) DO NOTHING;
