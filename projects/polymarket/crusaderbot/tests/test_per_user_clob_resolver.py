"""Per-user CLOB resolver + cross-user isolation assertion (Step 4).

These tests pin the SAFETY-CRITICAL contract: a key that resolves to a
different deposit wallet than the persisted column MUST NOT sign an
order. Drift = refuse, no auto-repair.
"""
from __future__ import annotations

import uuid as _uuid
from unittest.mock import AsyncMock, patch

import pytest

from projects.polymarket.crusaderbot.domain.execution.per_user_clob import (
    WalletIdentityMismatch,
    resolve_user_clob_client,
)
from projects.polymarket.crusaderbot.integrations.clob.exceptions import (
    ClobConfigError,
)
from projects.polymarket.crusaderbot.integrations.clob.user_client import (
    PerUserClobIsolationError,
)


_UID = _uuid.uuid4()
_ADDR = "0x3feC630a07a263Ee0bd6cD108ff4b8Ed1eB606A9"


class _StubSettings:
    """Minimal Settings stub — the resolver only forwards it."""
    USE_REAL_CLOB = True
    USE_PER_USER_EXECUTION = True
    POLYMARKET_BUILDER_CODE = ""
    POLYMARKET_BUILDER_ADDRESS = ""


class _Conn:
    def __init__(self, row) -> None:
        self._row = row
        self.queries: list[tuple] = []

    async def fetchrow(self, sql, *args):
        self.queries.append((sql, args))
        return self._row


# ── happy path ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_match_returns_client() -> None:
    """SDK address == stored address → return the cached client."""
    fake_client = object()
    conn = _Conn({"polymarket_deposit_wallet": _ADDR})
    with patch(
        "projects.polymarket.crusaderbot.domain.execution.per_user_clob"
        ".get_user_clob_client_with_wallet",
        AsyncMock(return_value=(fake_client, _ADDR)),
    ):
        out = await resolve_user_clob_client(
            user_id=_UID, conn=conn, settings=_StubSettings(),
        )
    assert out is fake_client


@pytest.mark.asyncio
async def test_match_is_case_insensitive() -> None:
    """SDK returns checksum; DB stores lowercase — must still match."""
    fake_client = object()
    conn = _Conn({"polymarket_deposit_wallet": _ADDR.lower()})
    with patch(
        "projects.polymarket.crusaderbot.domain.execution.per_user_clob"
        ".get_user_clob_client_with_wallet",
        AsyncMock(return_value=(fake_client, _ADDR.upper())),
    ):
        out = await resolve_user_clob_client(
            user_id=_UID, conn=conn, settings=_StubSettings(),
        )
    assert out is fake_client


# ── isolation invariants ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_drift_raises_wallet_identity_mismatch(caplog) -> None:
    """SDK address != stored address → refuse to sign. The exception is
    the in-code enforcement of the #1730 §4 cross-user isolation invariant
    (user A's order built with user B's funds is the catastrophic bug)."""
    fake_client = object()
    other = "0x" + "ab" * 20
    conn = _Conn({"polymarket_deposit_wallet": other})
    with patch(
        "projects.polymarket.crusaderbot.domain.execution.per_user_clob"
        ".get_user_clob_client_with_wallet",
        AsyncMock(return_value=(fake_client, _ADDR)),
    ):
        with pytest.raises(WalletIdentityMismatch, match="drift"):
            await resolve_user_clob_client(
                user_id=_UID, conn=conn, settings=_StubSettings(),
            )


@pytest.mark.asyncio
async def test_non_uuid_user_id_raises_isolation_error() -> None:
    """Defense-in-depth: a string user_id that bypassed upstream typing
    raises PerUserClobIsolationError (mirrors get_user_clob_client)."""
    with pytest.raises(PerUserClobIsolationError):
        await resolve_user_clob_client(
            user_id="not-a-uuid", conn=_Conn(None), settings=_StubSettings(),
        )


# ── null / missing column ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_null_deposit_wallet_raises_config_error() -> None:
    """A NULL column means the Step 2 backfill missed this user. The
    resolver REFUSES — there is no JIT auto-resolve on the trading hot
    path (the operator must run backfill_deposit_wallets() first)."""
    fake_client = object()
    conn = _Conn({"polymarket_deposit_wallet": None})
    with patch(
        "projects.polymarket.crusaderbot.domain.execution.per_user_clob"
        ".get_user_clob_client_with_wallet",
        AsyncMock(return_value=(fake_client, _ADDR)),
    ):
        with pytest.raises(ClobConfigError, match="backfill_deposit_wallets"):
            await resolve_user_clob_client(
                user_id=_UID, conn=conn, settings=_StubSettings(),
            )


@pytest.mark.asyncio
async def test_empty_string_deposit_wallet_is_treated_as_null() -> None:
    """A defensive guard: an empty string is as bad as NULL."""
    fake_client = object()
    conn = _Conn({"polymarket_deposit_wallet": ""})
    with patch(
        "projects.polymarket.crusaderbot.domain.execution.per_user_clob"
        ".get_user_clob_client_with_wallet",
        AsyncMock(return_value=(fake_client, _ADDR)),
    ):
        with pytest.raises(ClobConfigError, match="backfill_deposit_wallets"):
            await resolve_user_clob_client(
                user_id=_UID, conn=conn, settings=_StubSettings(),
            )


@pytest.mark.asyncio
async def test_missing_wallets_row_raises_config_error() -> None:
    """create_wallet_for_user has not run yet for this user."""
    fake_client = object()
    conn = _Conn(None)
    with patch(
        "projects.polymarket.crusaderbot.domain.execution.per_user_clob"
        ".get_user_clob_client_with_wallet",
        AsyncMock(return_value=(fake_client, _ADDR)),
    ):
        with pytest.raises(ClobConfigError, match="no wallets row"):
            await resolve_user_clob_client(
                user_id=_UID, conn=conn, settings=_StubSettings(),
            )


# ── wallet-aware client accessor ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_user_clob_client_with_wallet_returns_pair() -> None:
    """The user_client accessor returns (client, wallet) so the resolver
    can read the resolved wallet without a second SDK trip."""
    from projects.polymarket.crusaderbot.integrations.clob import user_client

    await user_client.clear_user_clob_cache()
    try:
        class _S:
            USE_REAL_CLOB = True
            POLYMARKET_BUILDER_CODE = ""
            POLYMARKET_BUILDER_ADDRESS = ""

        fake_client = object()
        fake_entry = user_client._CachedClient(
            client=fake_client, wallet=_ADDR, creds={}, created_at=0.0,
        )

        async def _fake_build(uid, settings):
            return fake_entry

        with patch.object(user_client, "_build_for_user", _fake_build):
            client, wallet = await user_client.get_user_clob_client_with_wallet(
                _UID, _S(),
            )
        assert client is fake_client
        assert wallet == _ADDR
    finally:
        await user_client.clear_user_clob_cache()
