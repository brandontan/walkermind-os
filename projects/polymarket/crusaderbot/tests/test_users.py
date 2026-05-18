"""Tests for users.py — seed_paper_capital and upsert_user new-user path.

Hermetic: no DB, no Telegram. Pool access patched via asyncpg context
manager fakes so all SQL is intercepted at the fetchval/execute level.
"""
from __future__ import annotations

import asyncio
import sys
from decimal import Decimal
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from projects.polymarket.crusaderbot import users as users_module
from projects.polymarket.crusaderbot.users import seed_paper_capital, upsert_user


# ---------------------------------------------------------------------------
# Pool / connection fakes
# ---------------------------------------------------------------------------

def _make_conn(*, balance, already_seeded: bool = False):
    """Return a fake asyncpg connection wired to the given wallet state."""
    conn = MagicMock()

    async def _fetchval(query, *args):
        if "balance_usdc" in query:
            return balance
        if "ledger" in query:
            return 1 if already_seeded else None
        return None

    async def _execute(query, *args):
        pass

    conn.fetchval = _fetchval
    conn.execute = AsyncMock(side_effect=_execute)
    conn.transaction = MagicMock(return_value=_ctx())
    return conn


def _ctx():
    """Minimal async context manager for conn.transaction()."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=None)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _make_pool(conn):
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_acquire_ctx(conn))
    return pool


def _acquire_ctx(conn):
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


# ---------------------------------------------------------------------------
# seed_paper_capital tests
# ---------------------------------------------------------------------------


def test_seed_paper_capital_credits_zero_wallet():
    """New wallet at $0 → returns True, execute called for UPDATE + INSERT."""
    conn = _make_conn(balance=Decimal("0"))
    pool = _make_pool(conn)

    with patch.object(users_module, "get_pool", return_value=pool):
        result = asyncio.run(seed_paper_capital(uuid4()))

    assert result is True
    # Two execute calls: UPDATE wallets + INSERT ledger
    assert conn.execute.call_count == 2
    update_call = conn.execute.call_args_list[0][0][0]
    insert_call = conn.execute.call_args_list[1][0][0]
    assert "UPDATE wallets" in update_call
    assert "INSERT INTO ledger" in insert_call


def test_seed_paper_capital_noop_when_balance_nonzero():
    """Wallet already has funds → returns False, no execute called."""
    conn = _make_conn(balance=Decimal("50"))
    pool = _make_pool(conn)

    with patch.object(users_module, "get_pool", return_value=pool):
        result = asyncio.run(seed_paper_capital(uuid4()))

    assert result is False
    conn.execute.assert_not_called()


def test_seed_paper_capital_noop_when_already_seeded():
    """Wallet at $0 but prior seed ledger entry exists → returns False, no execute."""
    conn = _make_conn(balance=Decimal("0"), already_seeded=True)
    pool = _make_pool(conn)

    with patch.object(users_module, "get_pool", return_value=pool):
        result = asyncio.run(seed_paper_capital(uuid4()))

    assert result is False
    conn.execute.assert_not_called()


def test_seed_paper_capital_noop_when_no_wallet():
    """No wallet row (fetchval returns None) → returns False, no exception."""
    conn = _make_conn(balance=None)
    pool = _make_pool(conn)

    with patch.object(users_module, "get_pool", return_value=pool):
        result = asyncio.run(seed_paper_capital(uuid4()))

    assert result is False
    conn.execute.assert_not_called()


# ---------------------------------------------------------------------------
# upsert_user new-user path
# ---------------------------------------------------------------------------


def test_upsert_user_new_user_seeds_paper_capital():
    """Full path: upsert_user for a new user triggers seed_paper_capital."""
    seeded: list[bool] = []

    async def _fake_seed(user_id):
        seeded.append(True)
        return True

    # Build a pool that returns a new user row on INSERT
    user_id = uuid4()
    row = {
        "id": user_id,
        "telegram_user_id": 999,
        "username": "tester",
        "access_tier": 2,
        "auto_trade_on": False,
        "paused": False,
        "locked": False,
        "onboarding_complete": False,
    }

    conn = MagicMock()
    # First fetchrow (SELECT) → None (new user)
    # Second fetchrow (INSERT RETURNING) → row
    conn.fetchrow = AsyncMock(side_effect=[None, row])
    conn.execute = AsyncMock()
    conn.transaction = MagicMock(return_value=_ctx())

    pool = _make_pool(conn)

    # Stub wallet.vault in sys.modules so the lazy import inside upsert_user resolves.
    vault_stub = ModuleType("projects.polymarket.crusaderbot.wallet.vault")
    vault_stub.create_wallet_for_user = AsyncMock()  # type: ignore[attr-defined]
    sys.modules.setdefault("projects.polymarket.crusaderbot.wallet.vault", vault_stub)

    with (
        patch.object(users_module, "get_pool", return_value=pool),
        patch.object(users_module, "seed_paper_capital", side_effect=_fake_seed),
    ):
        result = asyncio.run(upsert_user(telegram_user_id=999, username="tester"))

    assert seeded == [True], "seed_paper_capital must be called for new users"
    assert result["id"] == user_id
