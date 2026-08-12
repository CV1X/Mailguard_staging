-- Snapshot imutabil lunar de productivitate.
-- La prima accesare a unui raport pentru luna X, valorile calculate (coeficient,
-- ore planificate/disponibile, obiectiv real/minim, baza_procent, zile_lucratoare)
-- sunt persistate. Orice request ulterior pentru aceeași lună returnează valorile
-- fixate — concediile neplanificate, aprobările ulterioare și modificările de
-- obiective NU mai afectează targetele lunilor deja started.
--
-- Regula: snapshot-ul se creează automat la prima accesare (nu necesită acțiune manuală).
-- Modificare manuală: doar prin intervenție directă în CC project de către admin.

CREATE TABLE IF NOT EXISTS productivity_monthly_snapshot (
    id              BIGSERIAL PRIMARY KEY,
    department      TEXT NOT NULL,
    year            INTEGER NOT NULL,
    month           INTEGER NOT NULL,
    baza_procent    NUMERIC(6,2) NOT NULL,
    zile_lucratoare INTEGER NOT NULL,
    ore_planificate NUMERIC(10,2) NOT NULL,
    ore_disponibile NUMERIC(10,2) NOT NULL,
    coeficient      NUMERIC(10,4),
    obiectiv_real   NUMERIC(6,2),
    obiectiv_minim  NUMERIC(6,2),
    snapshot_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (department, year, month)
);

CREATE INDEX IF NOT EXISTS ix_prod_monthly_snapshot_dept_ym
    ON productivity_monthly_snapshot (department, year, month);
