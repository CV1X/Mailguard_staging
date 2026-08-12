"""AES-256-GCM encryption for IMAP credentials stored at rest.

Key source: PERSONAL_MAILBOX_KEY env var (64 hex chars = 32 bytes).
Generate once: python3 -c "import secrets; print(secrets.token_hex(32))"
"""
import os
import json
import base64
import secrets
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_NONCE_SIZE = 12  # 96-bit nonce, standard for GCM


def _key() -> bytes:
    raw = os.environ.get("PERSONAL_MAILBOX_KEY", "").strip()
    if not raw:
        raise RuntimeError("PERSONAL_MAILBOX_KEY not set in environment")
    try:
        key = bytes.fromhex(raw)
    except ValueError:
        raise RuntimeError("PERSONAL_MAILBOX_KEY must be 64 hex chars (32 bytes)")
    if len(key) != 32:
        raise RuntimeError("PERSONAL_MAILBOX_KEY must be exactly 32 bytes (64 hex chars)")
    return key


def encrypt_credentials(data: dict) -> str:
    """Encrypt dict to base64(nonce || ciphertext+tag). Raises if key missing."""
    plaintext = json.dumps(data, ensure_ascii=False).encode()
    nonce = secrets.token_bytes(_NONCE_SIZE)
    ct = AESGCM(_key()).encrypt(nonce, plaintext, None)
    return base64.b64encode(nonce + ct).decode()


def decrypt_credentials(blob: str) -> dict:
    """Decrypt base64 blob back to dict. Raises on tamper or key mismatch."""
    raw = base64.b64decode(blob)
    nonce, ct = raw[:_NONCE_SIZE], raw[_NONCE_SIZE:]
    plaintext = AESGCM(_key()).decrypt(nonce, ct, None)
    return json.loads(plaintext)
