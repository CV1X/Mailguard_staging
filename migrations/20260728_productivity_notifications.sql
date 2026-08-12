-- Destinatari email pentru rapoarte lunare de productivitate
-- Fiecare rând = un email + grupul de departamente pentru care primește raportul
-- department_group: 'operational' | 'financiar' | 'toate' | slug_departament individual
CREATE TABLE IF NOT EXISTS productivity_notifications (
    id               BIGSERIAL PRIMARY KEY,
    email            TEXT NOT NULL,
    department_group TEXT NOT NULL,
    enabled          BOOLEAN NOT NULL DEFAULT true,
    created_at       TIMESTAMPTZ DEFAULT now(),
    updated_at       TIMESTAMPTZ DEFAULT now(),
    UNIQUE (email, department_group)
);

CREATE INDEX IF NOT EXISTS pn_enabled_idx ON productivity_notifications (enabled);
