"""core/security/encryption.py — AES-256-GCM symmetric encryption for wallet private keys.

All encryption uses AES-256-GCM (authenticated encryption).  The key is
derived from the ``WALLET_SECRET_KEY`` environment variable via PBKDF2-HMAC-SHA256.

Rules:
    - NEVER log plaintext private keys.
    - NEVER return plaintext key outside of an explicit decrypt call.
    - Each encrypt call uses a fresh random 96-bit nonce (NIST recommended for GCM).
    - The salt and nonce are stored alongside the ciphertext (non-secret).
    - Fails loudly on missing env var — never silently encrypts with a weak key.

Ciphertext format (Base64-encoded binary):
    [ 16-byte salt | 12-byte nonce | N-byte ciphertext + 16-byte GCM tag ]
"""
from __future__ import annotations

import base64
import os
import secrets

import structlog
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

log = structlog.get_logger(__name__)

# ── Internal constants ─────────────────────────────────────────────────────────
_SALT_BYTES: int = 16
_NONCE_BYTES: int = 12
_PBKDF2_ITERATIONS: int = 260_000   # OWASP 2023 recommendation for PBKDF2-SHA256
_KEY_LENGTH: int = 32               # 256-bit AES key
_ENV_VAR: str = "WALLET_SECRET_KEY"
_AAD: bytes = b"polyquantbot-wallet-v1"   # additional authenticated data


# ── Key derivation ─────────────────────────────────────────────────────────────


def _derive_key(master_secret: bytes, salt: bytes) -> bytes:
    """Derive a 256-bit AES key from *master_secret* using PBKDF2-HMAC-SHA256.

    Args:
        master_secret: Raw bytes of the master secret (from env var).
        salt: 16-byte random salt unique per ciphertext.

    Returns:
        32-byte AES key.
    """
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=_KEY_LENGTH,
        salt=salt,
        iterations=_PBKDF2_ITERATIONS,
    )
    return kdf.derive(master_secret)


def _get_master_secret() -> bytes:
    """Load and validate the master secret from the environment.

    Raises:
        EnvironmentError: If ``WALLET_SECRET_KEY`` is not set or is empty.
    """
    secret = os.environ.get(_ENV_VAR, "").strip()
    if not secret:
        raise EnvironmentError(
            f"Environment variable '{_ENV_VAR}' is not set or empty. "
            "Set a strong random secret (at least 32 characters) before running."
        )
    return secret.encode()


# ── Public API ─────────────────────────────────────────────────────────────────


def encrypt_private_key(plaintext_hex_key: str) -> str:
    """Encrypt an Ethereum private key (hex string) using AES-256-GCM.

    A fresh random salt and nonce are generated for each call, ensuring
    that encrypting the same key twice produces different ciphertext.

    Args:
        plaintext_hex_key: 64-hex-character private key string (no ``0x`` prefix).

    Returns:
        Base64-encoded ciphertext string (salt + nonce + ciphertext + tag).

    Raises:
        EnvironmentError: If ``WALLET_SECRET_KEY`` is missing.
        ValueError: If the plaintext key is not a valid 32-byte hex string.
    """
    if not isinstance(plaintext_hex_key, str) or len(plaintext_hex_key) != 64:
        raise ValueError("Private key must be a 64-character hex string (32 bytes).")
    # Validate all-hex
    try:
        bytes.fromhex(plaintext_hex_key)
    except ValueError as exc:
        raise ValueError(f"Private key is not valid hex: {exc}") from exc

    master_secret = _get_master_secret()
    salt = secrets.token_bytes(_SALT_BYTES)
    nonce = secrets.token_bytes(_NONCE_BYTES)
    aes_key = _derive_key(master_secret, salt)

    aesgcm = AESGCM(aes_key)
    ciphertext_and_tag = aesgcm.encrypt(nonce, plaintext_hex_key.encode(), _AAD)

    # Pack: salt || nonce || ciphertext+tag
    blob = salt + nonce + ciphertext_and_tag
    encoded = base64.b64encode(blob).decode()

    log.debug(
        "private_key_encrypted",
        ciphertext_len=len(blob),
        # NEVER log the key or the plaintext
    )
    return encoded


def decrypt_private_key(encrypted_b64: str) -> str:
    """Decrypt an AES-256-GCM-encrypted private key back to its hex string.

    Args:
        encrypted_b64: Base64-encoded ciphertext produced by :func:`encrypt_private_key`.

    Returns:
        64-character hex private key string (no ``0x`` prefix).

    Raises:
        EnvironmentError: If ``WALLET_SECRET_KEY`` is missing.
        ValueError: If decryption fails (tampered data, wrong key, etc.).
    """
    master_secret = _get_master_secret()

    try:
        blob = base64.b64decode(encrypted_b64.encode())
    except Exception as exc:
        raise ValueError(f"Ciphertext is not valid Base64: {exc}") from exc

    min_len = _SALT_BYTES + _NONCE_BYTES + 1 + 16  # at least 1 byte payload + 16-byte GCM tag
    if len(blob) < min_len:
        raise ValueError(
            f"Ciphertext blob too short: {len(blob)} < {min_len} bytes."
        )

    salt = blob[:_SALT_BYTES]
    nonce = blob[_SALT_BYTES: _SALT_BYTES + _NONCE_BYTES]
    ciphertext_and_tag = blob[_SALT_BYTES + _NONCE_BYTES:]

    aes_key = _derive_key(master_secret, salt)
    aesgcm = AESGCM(aes_key)

    try:
        plaintext_bytes = aesgcm.decrypt(nonce, ciphertext_and_tag, _AAD)
    except Exception as exc:
        # Do NOT include exc details that might hint at key material
        log.error("private_key_decryption_failed", error_type=type(exc).__name__)
        raise ValueError("Decryption failed — invalid ciphertext or wrong secret key.") from exc

    return plaintext_bytes.decode()
