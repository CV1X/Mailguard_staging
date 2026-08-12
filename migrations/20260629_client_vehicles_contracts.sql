-- OPS-2026-0124 — vehicule + contracte per client (din CTS via sync clienti).
-- Aditiv si idempotent. INERT: tabelele raman goale pana cand IRIS expune
-- campurile vehicles[]/contracts[] pe /clients/contact-list (cerere catre Razvan).
-- Sync-ul existent de clienti le populeaza automat cand datele vor curge.

-- Vehiculele clientului
CREATE TABLE IF NOT EXISTS client_vehicles (
    id              bigserial PRIMARY KEY,
    client_id       bigint NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    iris_client_id  bigint,
    plate           text,            -- numar inmatriculare
    status          text,            -- activ / inactiv / radiat
    documents       jsonb NOT NULL DEFAULT '[]'::jsonb,  -- [{tip,status,data_expirare}]
    raw             jsonb,
    synced_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS client_vehicles_client_idx ON client_vehicles(client_id);
CREATE UNIQUE INDEX IF NOT EXISTS client_vehicles_uidx
    ON client_vehicles(client_id, lower(COALESCE(plate, '')));

-- Contractele clientului
CREATE TABLE IF NOT EXISTS client_contracts (
    id                bigserial PRIMARY KEY,
    client_id         bigint NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    iris_client_id    bigint,
    iris_contract_id  text,
    contract_type     text,
    start_date        date,
    end_date          date,
    status            text,          -- semnat / nesemnat / draft
    documents         jsonb NOT NULL DEFAULT '[]'::jsonb,  -- [{tip,status,data_incarcare}]
    vehicles          jsonb NOT NULL DEFAULT '[]'::jsonb,  -- ["B123ABC", ...] incadrate pe contract
    raw               jsonb,
    synced_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS client_contracts_client_idx ON client_contracts(client_id);
CREATE UNIQUE INDEX IF NOT EXISTS client_contracts_uidx
    ON client_contracts(
        client_id,
        lower(COALESCE(iris_contract_id, '')),
        lower(COALESCE(contract_type, '')),
        COALESCE(start_date, '0001-01-01'::date),
        COALESCE(end_date,   '0001-01-01'::date)
    );

-- Observabilitate sync (optional, citit de banner-ul din UI)
INSERT INTO settings(key, value, description) VALUES
  ('client_assets.last_result', 'null'::jsonb, 'OPS-0124: ultimul rezultat sync vehicule/contracte (informativ)')
ON CONFLICT (key) DO NOTHING;
