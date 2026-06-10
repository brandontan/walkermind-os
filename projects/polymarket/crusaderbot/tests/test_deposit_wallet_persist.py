"""Pre-resolved Polymarket deposit wallet (per-user execution Step 2).

Pins the contract: ``set_deposit_wallet_in_conn`` writes the SDK-resolved
deposit wallet inline with wallet creation, ``backfill_deposit_wallets``
populates existing rows sequentially and is idempotent, and a missing SDK is
logged + skipped (never raised) so wallet creation always lands.
"""
from __future__ import annotations

import uuid as _uuid
from unittest.mock import AsyncMock, patch

import pytest

from projects.polymarket.crusaderbot.wallet import deposit_wallet as _dw


class _Settings:
    WALLET_ENCRYPTION_KEY = "x" * 32


# ── conn-level writer ─────────────────────────────────────────────────────────

class _Conn:
    def __init__(self) -> None:
        self.executed: list[tuple] = []

    async def execute(self, sql, *args):
        self.executed.append((sql, args))
        return "OK"


@pytest.mark.asyncio
async def test_set_deposit_wallet_in_conn_writes_address() -> None:
    """Happy path: SDK resolves, UPDATE fires with the resolved address."""
    conn = _Conn()
    uid = _uuid.uuid4()
    resolved = "0xDeAdBeEf" + "11" * 16
    with patch.object(_dw, "_resolve", AsyncMock(return_value=resolved)):
        result = await _dw.set_deposit_wallet_in_conn(conn, uid, "0x" + "1" * 64)
    assert result == resolved
    assert any(
        "UPDATE wallets SET polymarket_deposit_wallet" in sql
        for sql, _ in conn.executed
    )
    # IS NULL guard preserves any value already on the row.
    assert any(
        "polymarket_deposit_wallet IS NULL" in sql for sql, _ in conn.executed
    )


@pytest.mark.asyncio
async def test_set_deposit_wallet_in_conn_returns_none_when_sdk_missing() -> None:
    """A missing polymarket SDK is logged + skipped — the column stays NULL."""
    conn = _Conn()

    async def _boom(_pk):
        raise _dw.DepositWalletDerivationUnavailable("simulated missing SDK")

    with patch.object(_dw, "_resolve", _boom):
        result = await _dw.set_deposit_wallet_in_conn(
            conn, _uuid.uuid4(), "0x" + "1" * 64,
        )
    assert result is None
    # No UPDATE issued when derivation unavailable — wallet creation still lands.
    assert conn.executed == []


@pytest.mark.asyncio
async def test_set_deposit_wallet_in_conn_returns_none_on_transient_failure() -> None:
    """A transient resolve failure (network, on-chain) returns None — wallet
    creation MUST land regardless; the backfill is the safety net."""
    conn = _Conn()

    async def _boom(_pk):
        raise RuntimeError("transient on-chain factory check failed")

    with patch.object(_dw, "_resolve", _boom):
        result = await _dw.set_deposit_wallet_in_conn(
            conn, _uuid.uuid4(), "0x" + "1" * 64,
        )
    assert result is None
    assert conn.executed == []


@pytest.mark.asyncio
async def test_set_deposit_wallet_in_conn_empty_key_propagates() -> None:
    """An empty signer key is a caller-side bug — PerUserClobError propagates
    (the explicit `except PerUserClobError: raise` clause, not swallowed by
    the broad transient-failure catch)."""
    from projects.polymarket.crusaderbot.integrations.clob.user_client import (
        PerUserClobError,
    )
    with pytest.raises(PerUserClobError, match="empty"):
        await _dw.set_deposit_wallet_in_conn(_Conn(), _uuid.uuid4(), "")


# ── backfill idempotency ──────────────────────────────────────────────────────

class _Txn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return None


class _BackfillConn:
    def __init__(self, rows_per_call):
        self._batches = list(rows_per_call)
        self.executed: list[tuple] = []

    async def fetch(self, _sql, _limit):
        return self._batches.pop(0) if self._batches else []

    async def execute(self, sql, *args):
        self.executed.append((sql, args))
        return "OK"

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


@pytest.mark.asyncio
async def test_backfill_idempotent_and_counts_correctly() -> None:
    """Backfill fills NULL rows, returns scanned/filled/skipped, exits on empty."""
    uid1, uid2 = _uuid.uuid4(), _uuid.uuid4()
    rows = [
        {"user_id": uid1, "encrypted_key": "enc1"},
        {"user_id": uid2, "encrypted_key": "enc2"},
    ]
    # First fetch returns the two rows; the WHERE IS NULL filter would already
    # have excluded any backfilled row, so the second fetch returns empty.
    conn = _BackfillConn([rows, []])

    resolve_mock = AsyncMock(side_effect=lambda pk: "0x" + pk[2:42])

    with patch.object(_dw, "get_settings", return_value=_Settings()), \
         patch.object(_dw, "get_pool", return_value=_Pool(conn)), \
         patch.object(_dw, "decrypt_pk", side_effect=lambda enc, _key: f"0x{enc * 32}"[:66]), \
         patch.object(_dw, "_resolve", resolve_mock):
        result = await _dw.backfill_deposit_wallets(batch_size=10)

    assert result == {"scanned": 2, "filled": 2, "skipped": 0}
    updates = [a for sql, a in conn.executed if "polymarket_deposit_wallet" in sql]
    assert len(updates) == 2
    # SEQUENTIAL invariant: one resolve call per row (not gathered).
    assert resolve_mock.await_count == 2


@pytest.mark.asyncio
async def test_backfill_aborts_cleanly_when_sdk_missing() -> None:
    """If derivation is unavailable, abort early and report what was done."""
    rows = [{"user_id": _uuid.uuid4(), "encrypted_key": "enc"}]
    conn = _BackfillConn([rows, []])

    async def _boom(_pk):
        raise _dw.DepositWalletDerivationUnavailable("simulated missing SDK")

    with patch.object(_dw, "get_settings", return_value=_Settings()), \
         patch.object(_dw, "get_pool", return_value=_Pool(conn)), \
         patch.object(_dw, "decrypt_pk", return_value="0x" + "1" * 64), \
         patch.object(_dw, "_resolve", _boom):
        result = await _dw.backfill_deposit_wallets(batch_size=10)

    assert result["filled"] == 0
    # No UPDATE fired — the column stays NULL for retry once the SDK is present.
    assert all("polymarket_deposit_wallet" not in sql for sql, _ in conn.executed)


@pytest.mark.asyncio
async def test_backfill_continues_past_per_user_resolve_failure() -> None:
    """One user's transient on-chain failure does NOT abort the whole batch —
    it's counted as skipped and the next user is attempted."""
    uid_ok, uid_bad = _uuid.uuid4(), _uuid.uuid4()
    rows = [
        {"user_id": uid_bad, "encrypted_key": "encX"},
        {"user_id": uid_ok, "encrypted_key": "encOK"},
    ]
    conn = _BackfillConn([rows, []])

    call_count = {"n": 0}

    async def _resolve(_pk):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("transient on-chain failure")
        return "0x" + "a" * 40

    with patch.object(_dw, "get_settings", return_value=_Settings()), \
         patch.object(_dw, "get_pool", return_value=_Pool(conn)), \
         patch.object(_dw, "decrypt_pk", return_value="0x" + "1" * 64), \
         patch.object(_dw, "_resolve", _resolve):
        result = await _dw.backfill_deposit_wallets(batch_size=10)

    assert result == {"scanned": 2, "filled": 1, "skipped": 1}
    updates = [a for sql, a in conn.executed if "polymarket_deposit_wallet" in sql]
    assert len(updates) == 1
    # Only the successful user's UPDATE fired.
    assert updates[0][0] == uid_ok


# ── vault wiring ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_wallet_pre_resolves_deposit_wallet() -> None:
    """Creating a user wallet must call set_deposit_wallet_in_conn inline,
    with the freshly-derived private key in scope (NOT the encrypted blob)."""
    from projects.polymarket.crusaderbot.wallet import vault

    class _VaultSettings:
        WALLET_HD_SEED = "test seed phrase"
        WALLET_ENCRYPTION_KEY = "x" * 32

    uid = _uuid.uuid4()
    row = {"deposit_address": "0xAbCd1234567890EF1234567890abcdef12345678", "hd_index": 1}

    class _VaultConn:
        async def execute(self, *_a, **_k):
            return "OK"

        async def fetchrow(self, *_a, **_k):
            return row

    pool = _Pool(_VaultConn())
    set_deposit_mock = AsyncMock(return_value="0xResolvedDepositWallet")

    with patch.object(vault, "get_settings", return_value=_VaultSettings()), \
         patch.object(vault, "next_hd_index", AsyncMock(return_value=1)), \
         patch.object(vault, "derive_address",
                      return_value=("0xAbCd1234567890EF1234567890abcdef12345678",
                                    "0xpk")), \
         patch.object(vault, "encrypt_pk", return_value="enc"), \
         patch.object(vault, "get_pool", return_value=pool), \
         patch.object(vault, "set_safe_address_in_conn", AsyncMock(return_value=None)), \
         patch.object(vault, "set_deposit_wallet_in_conn", set_deposit_mock):
        await vault.create_wallet_for_user(uid)

    set_deposit_mock.assert_awaited_once()
    args, _kwargs = set_deposit_mock.call_args
    # call signature is (conn, user_id, pk) — assert the UNENCRYPTED pk is
    # forwarded (so the SDK can sign), not the encrypted blob.
    assert args[1] == uid
    assert args[2] == "0xpk"
