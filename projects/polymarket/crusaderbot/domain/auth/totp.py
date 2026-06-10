"""Self-serve TOTP 2FA — RFC 6238.

Closes the documented gap in ``domain.activation.live_checklist._gate_two_factor``
(*"Self-serve 2FA infrastructure does not yet exist. Until it lands, the gate
reads system_settings for 2fa_enabled:{user_id} so the operator can manually
flip an account through"*).

Flow:

1. ``enroll(user_id, account_label)`` — generate a fresh base32 secret,
   Fernet-encrypt with ``WALLET_ENCRYPTION_KEY``, persist on
   ``user_settings.totp_secret_encrypted`` (overwrites any prior pending
   enrolment — the user has not yet enabled the new one). Returns the
   plaintext base32 secret + the otpauth provisioning URI so the user's
   authenticator app can be primed (QR rendered client-side).

2. ``verify_and_enable(user_id, code)`` — reads the encrypted secret,
   decrypts, runs RFC 6238 verify (±1 window tolerance for clock drift),
   on match: sets ``user_settings.totp_enabled=true`` AND writes
   ``system_settings[2fa_enabled:{user_id}]='true'`` so the existing
   live_checklist gate (``_gate_two_factor``) lights up automatically —
   the gate's read shape is preserved byte-for-byte.

3. ``verify_and_disable(user_id, code)`` — clears both flags (and the
   stored secret), requires a valid current code.

4. ``status(user_id)`` — non-secret read for the UI: enrolled / enabled
   bools, never returns the secret.

Design notes:

* TOTP secret is encrypted at rest with the existing ``WALLET_ENCRYPTION_KEY``
  Fernet (same key the HD private keys are encrypted with) — adding a separate
  key surface here would create a new operator burden for no isolation gain
  (anyone with DB access AND the existing key already controls trading).
* ``pyotp`` is the canonical RFC 6238 implementation, widely used, no native
  deps; pinned in ``pyproject.toml``.
* The ``system_settings[2fa_enabled:{user_id}]`` write is a deliberate keep:
  it preserves the existing live_checklist gate's read shape so this lane
  changes ONE write site rather than touching the gate's read site. A later
  cleanup can collapse to a single column once every read is migrated.
"""
from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken

from ...config import get_settings
from ...database import get_pool

logger = logging.getLogger(__name__)


# ── exceptions ───────────────────────────────────────────────────────────────


class TotpError(Exception):
    """Base class for TOTP-related errors."""


class TotpNotEnrolled(TotpError):
    """The user has no encrypted secret on file — enroll first."""


class TotpInvalidCode(TotpError):
    """The 6-digit code did not match the stored secret (within window)."""


class TotpDecryptionError(TotpError):
    """The stored secret could not be decrypted — likely a key rotation bug.

    Raised so the caller can surface a clean error rather than silently
    refusing every code (which would look identical to an invalid code and
    permanently lock the user out without a clear cause).
    """


# ── primitives ───────────────────────────────────────────────────────────────


def _fernet() -> Fernet:
    return Fernet(get_settings().WALLET_ENCRYPTION_KEY.encode())


def generate_secret() -> str:
    """Return a fresh base32-encoded TOTP secret (160 bits = 32 chars)."""
    import pyotp  # noqa: WPS433 — lazy so module import is cheap
    return pyotp.random_base32()


def provisioning_uri(secret: str, account_label: str, issuer: str = "CrusaderBot") -> str:
    """Build the ``otpauth://totp/...`` URI for an authenticator app QR."""
    import pyotp  # noqa: WPS433
    return pyotp.TOTP(secret).provisioning_uri(name=account_label, issuer_name=issuer)


def verify_code(secret: str, code: str) -> bool:
    """RFC 6238 verify with ±1 30-second window tolerance for clock drift."""
    import pyotp  # noqa: WPS433
    if not code:
        return False
    # ``valid_window=1`` accepts the previous OR next 30s window on top of the
    # current one — robust against ~30s of clock skew between the user's phone
    # and the server. Tighter than the 2-3 window some apps use because the
    # gate guards real-money trading; balance security vs UX.
    return bool(pyotp.TOTP(secret).verify(str(code).strip(), valid_window=1))


# ── DB helpers ───────────────────────────────────────────────────────────────


async def _read_secret(user_id: UUID) -> Optional[str]:
    """Read + decrypt the user's stored TOTP secret. Returns None if not
    enrolled (no encrypted blob on the row)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT totp_secret_encrypted FROM user_settings WHERE user_id=$1",
            user_id,
        )
    if row is None or not row["totp_secret_encrypted"]:
        return None
    try:
        return _fernet().decrypt(row["totp_secret_encrypted"].encode()).decode()
    except InvalidToken as exc:
        raise TotpDecryptionError(
            f"totp secret decrypt failed for user={user_id} (key rotation?)"
        ) from exc


# ── public API ───────────────────────────────────────────────────────────────


async def enroll(user_id: UUID, account_label: str) -> dict:
    """Generate + persist a fresh TOTP secret. Returns ``{secret, otpauth_uri}``.

    Idempotent in spirit: calling repeatedly REPLACES any prior pending
    enrolment (the user has not yet verified the new one) — that lets the
    user re-roll if they lost the QR before scanning. Once
    ``verify_and_enable`` succeeds, re-enrolling rotates the secret; the
    next ``verify_and_enable`` re-affirms the flag.

    The user_settings row is upserted defensively: a brand-new user who
    arrives at the 2FA setup page before any other settings write would
    otherwise hit a NULL row.
    """
    secret = generate_secret()
    encrypted = _fernet().encrypt(secret.encode()).decode()
    pool = get_pool()
    async with pool.acquire() as conn:
        # INSERT with all known defaults (matches migration 052), UPDATE the
        # secret column on conflict. user_settings.user_id is the PK from
        # migration 001.
        await conn.execute(
            "INSERT INTO user_settings (user_id, totp_secret_encrypted) "
            "VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET "
            "totp_secret_encrypted=EXCLUDED.totp_secret_encrypted",
            user_id, encrypted,
        )
    return {
        "secret": secret,
        "otpauth_uri": provisioning_uri(secret, account_label),
    }


async def verify_and_enable(user_id: UUID, code: str) -> None:
    """Validate the 6-digit code against the stored secret. On success: set
    ``totp_enabled=true`` AND write the legacy ``system_settings`` flag so
    live_checklist gate 7 passes.

    Raises:
        TotpNotEnrolled: no encrypted secret on file (user hasn't called
            ``enroll`` yet).
        TotpInvalidCode: code is wrong / expired.
        TotpDecryptionError: stored secret cannot be decrypted (operator
            issue — surface to logs + tell the user to re-enroll).
    """
    secret = await _read_secret(user_id)
    if secret is None:
        raise TotpNotEnrolled("user has not enrolled a TOTP secret yet")
    if not verify_code(secret, code):
        raise TotpInvalidCode("totp code did not match")
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "UPDATE user_settings SET totp_enabled=TRUE WHERE user_id=$1",
                user_id,
            )
            # Same transaction-spanning intent: flip the column + the legacy
            # flag the gate reads, atomically. The system_settings upsert
            # uses the same connection so both writes commit together.
            key = f"2fa_enabled:{user_id}"
            await conn.execute(
                "INSERT INTO system_settings (key, value) VALUES ($1, 'true') "
                "ON CONFLICT (key) DO UPDATE SET value='true'",
                key,
            )


async def verify_and_disable(user_id: UUID, code: str) -> None:
    """Validate the current code, then clear secret + flags.

    Requires a valid code so a stolen session cannot turn 2FA off without
    the second factor. Raises the same exceptions as ``verify_and_enable``.
    """
    secret = await _read_secret(user_id)
    if secret is None:
        raise TotpNotEnrolled("user has not enrolled a TOTP secret yet")
    if not verify_code(secret, code):
        raise TotpInvalidCode("totp code did not match")
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "UPDATE user_settings SET totp_enabled=FALSE, "
                "totp_secret_encrypted=NULL WHERE user_id=$1",
                user_id,
            )
            key = f"2fa_enabled:{user_id}"
            await conn.execute(
                "INSERT INTO system_settings (key, value) VALUES ($1, 'false') "
                "ON CONFLICT (key) DO UPDATE SET value='false'",
                key,
            )


async def status(user_id: UUID) -> dict:
    """Non-secret read for the UI: ``{enrolled, enabled}``.

    ``enrolled`` = there is an encrypted secret on file (setup in flight or
    complete). ``enabled`` = ``totp_enabled=true`` (verify confirmed it).
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT totp_secret_encrypted, totp_enabled "
            "FROM user_settings WHERE user_id=$1",
            user_id,
        )
    if row is None:
        return {"enrolled": False, "enabled": False}
    return {
        "enrolled": bool(row["totp_secret_encrypted"]),
        "enabled": bool(row["totp_enabled"]),
    }
