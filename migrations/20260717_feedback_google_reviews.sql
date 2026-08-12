-- T6: Rutare către Google Reviews după completarea feedback-ului.
-- Idempotent. NU se adaugă nicio coloană de filtrare pe rating pe acest
-- config — decizia agreată e no-gating (link afișat necondiționat, vezi
-- CLAUDE.md / nota T6). Feedback-ul (inclusiv negativ) rămâne salvat
-- integral și separat în feedback_kpi_ratings (T4), neschimbat de T6.

CREATE TABLE IF NOT EXISTS feedback_google_config (
    id          bigserial PRIMARY KEY,
    review_url  varchar(500) NOT NULL,
    active      boolean NOT NULL DEFAULT true,
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- Config unică (single-row) — la fel ca feedback_email_config (T5).
CREATE UNIQUE INDEX IF NOT EXISTS idx_feedback_google_config_singleton
    ON feedback_google_config((true));
