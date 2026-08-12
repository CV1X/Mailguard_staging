-- R6: UNIQUE constraint pe api_keys.key_hash (prevenire duplicate la regenerare cheie)
CREATE UNIQUE INDEX IF NOT EXISTS uq_api_keys_key_hash ON api_keys(key_hash);
