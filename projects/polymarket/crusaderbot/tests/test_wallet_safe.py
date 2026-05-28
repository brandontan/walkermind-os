"""Pre-computed Safe-proxy address (custody migration chunk 2).

Pins the contract: derivation is deterministic + local (no creds, no network),
backfill is idempotent, and wallet creation populates the column inline.
"""
from __future__ import annotations

import uuid as _uuid
from unittest.mock import AsyncMock, patch

import pytest

from projects.polymarket.crusaderbot.wallet import safe as _safe


class _Settings:
    POLY_RELAYER_URL = "https://relayer-v2.polymarket.com"
    WALLET_ENCRYPTION_KEY = "x" * 32


# ── derivation ────────────────────────────────────────────────────────────────

def test_compute_safe_address_is_deterministic() -> None:
    pytest.importorskip("py_builder_relayer_client")
    pk = "0x" + "1" * 64
    with patch.object(_safe, "get_settings", return_value=_Settings()):
        a = _safe.compute_safe_address(pk)
        b = _safe.compute_safe_address(pk)
    # Same input → same Safe address (CREATE2 is deterministic).
    assert a == b
    assert a.startswith("0x") and len(a) == 42


def test_compute_safe_address_distinct_keys_distinct_addresses() -> None:
    pytest.importorskip("py_builder_relayer_client")
    with patch.object(_safe, "get_settings", return_value=_Settings()):
        a = _safe.compute_safe_address("0x" + "1" * 64)
        b = _safe.compute_safe_address("0x" + "2" * 64)
    assert a != b


def test_compute_safe_address_rejects_empty_key() -> None:
    with pytest.raises(ValueError, match="empty signer key"):
        _safe.compute_safe_address("")


# ── conn-level writer ─────────────────────────────────────────────────────────

class _Conn:
    def __init__(self) -> None:
        self.executed: list[tuple] = []

    async def execute(self, sql, *args):
        self.executed.append((sql, args))
        return "OK"


@pytest.mark.asyncio
async def test_set_safe_address_in_conn_writes_address() -> None:
    pytest.importorskip("py_builder_relayer_client")
    conn = _Conn()
    uid = _uuid.uuid4()
    with patch.object(_safe, "get_settings", return_value=_Settings()):
        result = await _safe.set_safe_address_in_conn(conn, uid, "0x" + "1" * 64)
    assert result is not None and result.startswith("0x")
    assert any("UPDATE wallets SET safe_address" in sql for sql, _ in conn.executed)


@pytest.mark.asyncio
async def test_set_safe_address_in_conn_returns_none_when_sdk_missing() -> None:
    """A missing SDK is logged + skipped, never raised — the column stays NULL."""
    conn = _Conn()

    def _boom(_pk):
        raise _safe.SafeDerivationUnavailable("simulated missing SDK")

    with patch.object(_safe, "compute_safe_address", _boom):
        result = await _safe.set_safe_address_in_conn(
            conn, _uuid.uuid4(), "0x" + "1" * 64,
        )
    assert result is None
    assert conn.executed == []  # no UPDATE issued when derivation unavailable


# ── backfill idempotency ──────────────────────────────────────────────────────

class _Txn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return None


class _BackfillConn:
    def __init__(self, rows_per_call):
        # rows_per_call: list of row-batches to return on successive fetches.
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
    # First fetch returns the two rows; second returns empty (loop exits).
    conn = _BackfillConn([rows, []])

    with patch.object(_safe, "get_settings", return_value=_Settings()), \
         patch.object(_safe, "get_pool", return_value=_Pool(conn)), \
         patch.object(_safe, "decrypt_pk", side_effect=lambda enc, _key: f"0x{enc * 32}"[:66]), \
         patch.object(_safe, "compute_safe_address",
                      side_effect=lambda pk: "0x" + pk[2:42]):
        result = await _safe.backfill_safe_addresses(batch_size=10)

    assert result == {"scanned": 2, "filled": 2, "skipped": 0}
    updates = [a for sql, a in conn.executed if "safe_address" in sql]
    assert len(updates) == 2


@pytest.mark.asyncio
async def test_backfill_aborts_cleanly_when_sdk_missing() -> None:
    """If derivation is unavailable, abort early and report what was done."""
    rows = [{"user_id": _uuid.uuid4(), "encrypted_key": "enc"}]
    conn = _BackfillConn([rows, []])

    def _boom(_pk):
        raise _safe.SafeDerivationUnavailable("simulated missing SDK")

    with patch.object(_safe, "get_settings", return_value=_Settings()), \
         patch.object(_safe, "get_pool", return_value=_Pool(conn)), \
         patch.object(_safe, "decrypt_pk", return_value="0x" + "1" * 64), \
         patch.object(_safe, "compute_safe_address", _boom):
        result = await _safe.backfill_safe_addresses(batch_size=10)

    assert result["filled"] == 0
    assert all("safe_address" not in sql for sql, _ in conn.executed)


# ── vault wiring ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_wallet_pre_computes_safe_address() -> None:
    """Creating a user wallet must call set_safe_address_in_conn inline."""
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
    set_safe_mock = AsyncMock(return_value="0xSafe")

    with patch.object(vault, "get_settings", return_value=_VaultSettings()), \
         patch.object(vault, "next_hd_index", AsyncMock(return_value=1)), \
         patch.object(vault, "derive_address",
                      return_value=("0xAbCd1234567890EF1234567890abcdef12345678",
                                    "0xpk")), \
         patch.object(vault, "encrypt_pk", return_value="enc"), \
         patch.object(vault, "get_pool", return_value=pool), \
         patch.object(vault, "set_safe_address_in_conn", set_safe_mock):
        await vault.create_wallet_for_user(uid)

    set_safe_mock.assert_awaited_once()
    args, _kwargs = set_safe_mock.call_args
    # call signature is (conn, user_id, pk) — assert the pk is forwarded
    assert args[1] == uid
    assert args[2] == "0xpk"
