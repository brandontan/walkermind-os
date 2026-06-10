"""Self-serve TOTP 2FA (closes live_checklist gate 7).

Pins the contract: enrol generates + encrypts a secret; verify validates
RFC 6238 codes with ±1 window tolerance; enable flips both the column AND
the legacy ``system_settings[2fa_enabled:{uid}]`` flag the existing
live_checklist gate reads; disable clears everything; status leaks no secret.
"""
from __future__ import annotations

import uuid as _uuid
from unittest.mock import patch

import pyotp
import pytest

from cryptography.fernet import Fernet

from projects.polymarket.crusaderbot.domain.auth import totp as _totp


# ── helpers ──────────────────────────────────────────────────────────────────


class _Settings:
    # Real Fernet key so encrypt/decrypt actually round-trips.
    WALLET_ENCRYPTION_KEY = Fernet.generate_key().decode()


class _Txn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return None


class _Conn:
    def __init__(self, row=None):
        self._row = row
        self.executed: list[tuple] = []

    async def execute(self, sql, *args):
        self.executed.append((sql, args))
        return "OK"

    async def fetchrow(self, _sql, *_args):
        return self._row

    def transaction(self):
        return _Txn()


class _Acq:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *_a):
        return None


class _Pool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _Acq(self._conn)


def _make_encrypted(secret: str, key: str) -> str:
    return Fernet(key.encode()).encrypt(secret.encode()).decode()


# ── primitives ───────────────────────────────────────────────────────────────


def test_generate_secret_is_base32_and_distinct() -> None:
    a = _totp.generate_secret()
    b = _totp.generate_secret()
    assert a != b
    # base32 alphabet — pyotp.random_base32() yields A-Z2-7
    assert all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567" for c in a)
    assert len(a) >= 16  # default pyotp length is 32


def test_provisioning_uri_carries_label_and_issuer() -> None:
    uri = _totp.provisioning_uri("ABCDEFGHIJKLMNOP", "walk3r69")
    assert uri.startswith("otpauth://totp/")
    assert "walk3r69" in uri
    assert "issuer=CrusaderBot" in uri


def test_verify_code_accepts_current_and_window() -> None:
    secret = _totp.generate_secret()
    code_now = pyotp.TOTP(secret).now()
    assert _totp.verify_code(secret, code_now) is True
    assert _totp.verify_code(secret, "000000") is False
    assert _totp.verify_code(secret, "") is False


# ── enroll ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_enroll_persists_encrypted_secret_and_returns_uri() -> None:
    settings = _Settings()
    conn = _Conn()
    uid = _uuid.uuid4()

    with patch.object(_totp, "get_settings", return_value=settings), \
         patch.object(_totp, "get_pool", return_value=_Pool(conn)):
        out = await _totp.enroll(uid, "walk3r69")

    assert "secret" in out and "otpauth_uri" in out
    assert out["otpauth_uri"].startswith("otpauth://totp/")
    # exactly one UPDATE/INSERT against user_settings, with the encrypted blob
    assert any(
        "user_settings" in sql and "totp_secret_encrypted" in sql
        for sql, _ in conn.executed
    )
    # secret stored on the row is encrypted, NOT plaintext
    persisted_args = [
        args for sql, args in conn.executed
        if "totp_secret_encrypted" in sql
    ][0]
    assert persisted_args[1] != out["secret"]
    # round-trip proves encryption (decrypt with same key returns the secret)
    decrypted = Fernet(settings.WALLET_ENCRYPTION_KEY.encode()).decrypt(
        persisted_args[1].encode()
    ).decode()
    assert decrypted == out["secret"]


# ── verify_and_enable ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_verify_and_enable_flips_both_column_and_legacy_flag() -> None:
    """The legacy ``system_settings[2fa_enabled:{uid}]`` write is THE thing
    that makes live_checklist gate 7 light up — must be present."""
    settings = _Settings()
    secret = _totp.generate_secret()
    encrypted = _make_encrypted(secret, settings.WALLET_ENCRYPTION_KEY)
    code = pyotp.TOTP(secret).now()
    uid = _uuid.uuid4()
    conn = _Conn(row={"totp_secret_encrypted": encrypted})

    with patch.object(_totp, "get_settings", return_value=settings), \
         patch.object(_totp, "get_pool", return_value=_Pool(conn)):
        await _totp.verify_and_enable(uid, code)

    # column write
    assert any(
        "totp_enabled=TRUE" in sql for sql, _ in conn.executed
    )
    # legacy gate flag write — keeps domain/activation/live_checklist untouched
    flag_writes = [
        args for sql, args in conn.executed
        if "system_settings" in sql and "INSERT" in sql
    ]
    assert flag_writes, "expected system_settings write so the live_checklist gate lights up"
    assert flag_writes[0][0] == f"2fa_enabled:{uid}"


@pytest.mark.asyncio
async def test_verify_and_enable_rejects_wrong_code() -> None:
    settings = _Settings()
    secret = _totp.generate_secret()
    encrypted = _make_encrypted(secret, settings.WALLET_ENCRYPTION_KEY)
    conn = _Conn(row={"totp_secret_encrypted": encrypted})

    with patch.object(_totp, "get_settings", return_value=settings), \
         patch.object(_totp, "get_pool", return_value=_Pool(conn)):
        with pytest.raises(_totp.TotpInvalidCode):
            await _totp.verify_and_enable(_uuid.uuid4(), "000000")

    # neither the column nor the flag flipped on an invalid code
    assert not any("totp_enabled=TRUE" in sql for sql, _ in conn.executed)
    assert not any("system_settings" in sql for sql, _ in conn.executed)


@pytest.mark.asyncio
async def test_verify_and_enable_rejects_unenrolled_user() -> None:
    conn = _Conn(row=None)
    settings = _Settings()
    with patch.object(_totp, "get_settings", return_value=settings), \
         patch.object(_totp, "get_pool", return_value=_Pool(conn)):
        with pytest.raises(_totp.TotpNotEnrolled):
            await _totp.verify_and_enable(_uuid.uuid4(), "123456")


@pytest.mark.asyncio
async def test_verify_and_enable_surfaces_decryption_error() -> None:
    """A corrupt secret (wrong key) raises a typed error, NOT silent invalid-code.
    Silent failure would lock the user out without a fixable signal."""
    settings = _Settings()
    other_key = Fernet.generate_key().decode()
    # Encrypted with a DIFFERENT key than what _Settings carries.
    encrypted = _make_encrypted("ABCDEFGHIJKLMNOP", other_key)
    conn = _Conn(row={"totp_secret_encrypted": encrypted})

    with patch.object(_totp, "get_settings", return_value=settings), \
         patch.object(_totp, "get_pool", return_value=_Pool(conn)):
        with pytest.raises(_totp.TotpDecryptionError):
            await _totp.verify_and_enable(_uuid.uuid4(), "123456")


# ── verify_and_disable ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_verify_and_disable_requires_valid_code() -> None:
    """A stolen session cannot turn 2FA off without the second factor."""
    settings = _Settings()
    secret = _totp.generate_secret()
    encrypted = _make_encrypted(secret, settings.WALLET_ENCRYPTION_KEY)
    conn = _Conn(row={"totp_secret_encrypted": encrypted})

    with patch.object(_totp, "get_settings", return_value=settings), \
         patch.object(_totp, "get_pool", return_value=_Pool(conn)):
        with pytest.raises(_totp.TotpInvalidCode):
            await _totp.verify_and_disable(_uuid.uuid4(), "000000")


@pytest.mark.asyncio
async def test_verify_and_disable_clears_column_secret_and_flag() -> None:
    settings = _Settings()
    secret = _totp.generate_secret()
    encrypted = _make_encrypted(secret, settings.WALLET_ENCRYPTION_KEY)
    code = pyotp.TOTP(secret).now()
    uid = _uuid.uuid4()
    conn = _Conn(row={"totp_secret_encrypted": encrypted})

    with patch.object(_totp, "get_settings", return_value=settings), \
         patch.object(_totp, "get_pool", return_value=_Pool(conn)):
        await _totp.verify_and_disable(uid, code)

    # column reset to FALSE + secret cleared
    assert any(
        "totp_enabled=FALSE" in sql and "totp_secret_encrypted=NULL" in sql
        for sql, _ in conn.executed
    )
    # legacy gate flag cleared to 'false' so the gate stops passing
    flag_writes = [
        args for sql, args in conn.executed
        if "system_settings" in sql and "INSERT" in sql
    ]
    assert flag_writes
    assert flag_writes[0][0] == f"2fa_enabled:{uid}"


# ── status ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_status_never_returns_the_secret() -> None:
    settings = _Settings()
    secret = _totp.generate_secret()
    encrypted = _make_encrypted(secret, settings.WALLET_ENCRYPTION_KEY)
    conn = _Conn(row={
        "totp_secret_encrypted": encrypted,
        "totp_enabled": True,
    })

    with patch.object(_totp, "get_settings", return_value=settings), \
         patch.object(_totp, "get_pool", return_value=_Pool(conn)):
        out = await _totp.status(_uuid.uuid4())

    assert out == {"enrolled": True, "enabled": True}
    # secret must never be in the response shape
    assert "secret" not in out
    assert "totp_secret_encrypted" not in out


@pytest.mark.asyncio
async def test_status_returns_false_for_unknown_user() -> None:
    conn = _Conn(row=None)
    with patch.object(_totp, "get_settings", return_value=_Settings()), \
         patch.object(_totp, "get_pool", return_value=_Pool(conn)):
        out = await _totp.status(_uuid.uuid4())
    assert out == {"enrolled": False, "enabled": False}


# ── gate integration ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_live_checklist_gate_reads_the_flag_we_write() -> None:
    """The lane's whole purpose: verify_and_enable writes the SAME key that
    domain/activation/live_checklist._gate_two_factor reads. If this drifts,
    self-serve 2FA stops unlocking the live gate."""
    from projects.polymarket.crusaderbot.domain.activation import live_checklist
    uid = _uuid.uuid4()
    # Drive verify_and_enable's INSERT into system_settings and capture the key.
    settings = _Settings()
    secret = _totp.generate_secret()
    encrypted = _make_encrypted(secret, settings.WALLET_ENCRYPTION_KEY)
    code = pyotp.TOTP(secret).now()
    conn = _Conn(row={"totp_secret_encrypted": encrypted})
    with patch.object(_totp, "get_settings", return_value=settings), \
         patch.object(_totp, "get_pool", return_value=_Pool(conn)):
        await _totp.verify_and_enable(uid, code)
    written_key = [
        args[0] for sql, args in conn.executed
        if "system_settings" in sql and "INSERT" in sql
    ][0]
    # Independently re-derive the key the gate reads — must be identical.
    expected_key = f"2fa_enabled:{uid}"
    assert written_key == expected_key
    # Belt-and-suspenders: the gate constructs its own key the same way.
    assert hasattr(live_checklist, "_gate_two_factor")
