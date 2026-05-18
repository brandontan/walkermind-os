"""Tests for backfill_missing_wallets in users.py.

Hermetic: no DB, no Telegram. Follows the test_users.py pattern:
top-level import + patch.object to intercept DB calls.

wallet.vault is mocked via sys.modules before each call because it
imports `cryptography` (a C extension) which may not be available in
all test environments.

Scenarios:
  A — user exists without wallet row → backfill creates wallet + seeds capital
  B — run backfill twice on same user → idempotent, no duplicate
  C — user already has wallet → backfill skips cleanly (count = 0)
  D — DB failure during startup query → returns 0, does not raise
"""
from __future__ import annotations

import asyncio
import sys
from types import ModuleType
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

from projects.polymarket.crusaderbot import users as users_module
from projects.polymarket.crusaderbot.users import backfill_missing_wallets

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

_NO_WALLET_USER = UUID("11111111-1111-1111-1111-111111111111")
_HAS_WALLET_USER = UUID("22222222-2222-2222-2222-222222222222")

_VAULT_KEY = "projects.polymarket.crusaderbot.wallet.vault"
_WALLET_PKG_KEY = "projects.polymarket.crusaderbot.wallet"


class _BackfillConn:
    """Simulates the pool connection used inside backfill_missing_wallets.

    Returns `missing_ids` for the discovery SELECT, empty list otherwise.
    """

    def __init__(self, missing_ids: list[UUID]) -> None:
        self._missing = missing_ids

    async def fetch(self, sql: str, *args: Any) -> list[dict]:
        if "NOT IN" in sql and "wallets" in sql:
            return [{"id": uid} for uid in self._missing]
        return []


def _make_pool(conn: _BackfillConn) -> MagicMock:
    pool = MagicMock()
    acm = MagicMock()
    acm.__aenter__ = AsyncMock(return_value=conn)
    acm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = acm
    return pool


def _vault_mock(create_fn=None) -> ModuleType:
    """Build a fake wallet.vault module with an injectable create_wallet_for_user."""
    mod = ModuleType("vault")
    mod.create_wallet_for_user = create_fn or AsyncMock()
    return mod


def _run(pool, create_fn=None, seed_fn=None):
    """Helper: run backfill_missing_wallets with mocked vault + seed."""
    vault = _vault_mock(create_fn)
    seed = seed_fn or AsyncMock(return_value=True)
    with (
        patch.dict(sys.modules, {_VAULT_KEY: vault}),
        patch.object(users_module, "seed_paper_capital", new=seed),
    ):
        return asyncio.run(backfill_missing_wallets(pool)), vault, seed


# ---------------------------------------------------------------------------
# Scenario A — user without wallet gets one created
# ---------------------------------------------------------------------------

class TestBackfillCreatesWallet:
    def test_wallet_created_for_user_missing_one(self):
        create_mock = AsyncMock()
        count, vault, seed = _run(
            _make_pool(_BackfillConn([_NO_WALLET_USER])),
            create_fn=create_mock,
        )
        assert count == 1, f"Expected 1 wallet created, got {count}"
        create_mock.assert_awaited_once_with(_NO_WALLET_USER)
        seed.assert_awaited_once_with(_NO_WALLET_USER)

    def test_returns_correct_count_for_multiple_missing(self):
        uid1, uid2, uid3 = uuid4(), uuid4(), uuid4()
        create_mock = AsyncMock()
        count, _, seed = _run(
            _make_pool(_BackfillConn([uid1, uid2, uid3])),
            create_fn=create_mock,
        )
        assert count == 3
        assert create_mock.await_count == 3
        assert seed.await_count == 3


# ---------------------------------------------------------------------------
# Scenario B — idempotent: second run on same user does nothing
# ---------------------------------------------------------------------------

class TestBackfillIdempotent:
    def test_second_run_returns_zero_when_all_wallets_exist(self):
        create_mock = AsyncMock()
        seed_mock = AsyncMock(return_value=False)
        count, _, _ = _run(
            _make_pool(_BackfillConn([])),
            create_fn=create_mock,
            seed_fn=seed_mock,
        )
        assert count == 0, f"Expected 0 on second run, got {count}"
        create_mock.assert_not_awaited()
        seed_mock.assert_not_awaited()

    def test_two_consecutive_runs_total_count(self):
        """First run creates 1; second run (nothing missing) creates 0."""
        uid = uuid4()
        call_count = 0

        async def _idempotent_create(user_id: UUID) -> None:
            nonlocal call_count
            call_count += 1

        seed_mock = AsyncMock(return_value=True)
        vault = _vault_mock(_idempotent_create)

        with (
            patch.dict(sys.modules, {_VAULT_KEY: vault}),
            patch.object(users_module, "seed_paper_capital", new=seed_mock),
        ):
            first = asyncio.run(backfill_missing_wallets(_make_pool(_BackfillConn([uid]))))
            second = asyncio.run(backfill_missing_wallets(_make_pool(_BackfillConn([]))))

        assert first == 1
        assert second == 0
        assert call_count == 1  # create_wallet called only on first run


# ---------------------------------------------------------------------------
# Scenario C — user already has wallet → backfill skips
# ---------------------------------------------------------------------------

class TestBackfillSkipsExisting:
    def test_only_missing_users_get_wallet_created(self):
        """SELECT ... WHERE id NOT IN (wallets) correctly excludes wallet owners."""
        create_mock = AsyncMock()
        count, _, _ = _run(
            _make_pool(_BackfillConn([_NO_WALLET_USER])),
            create_fn=create_mock,
        )
        assert count == 1
        for call_args in create_mock.await_args_list:
            called_uid = call_args.args[0]
            assert called_uid != _HAS_WALLET_USER, (
                "backfill incorrectly called create_wallet for user with existing wallet"
            )

    def test_empty_missing_list_creates_nothing(self):
        create_mock = AsyncMock()
        count, _, seed = _run(_make_pool(_BackfillConn([])), create_fn=create_mock)
        assert count == 0
        create_mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# Scenario D — DB failure → returns 0, does not raise
# ---------------------------------------------------------------------------

class TestBackfillFailSafe:
    def test_db_error_on_discovery_returns_zero(self):
        """Pool connection raises → backfill logs and returns 0."""

        class _BrokenConn:
            async def fetch(self, sql: str, *args: Any) -> list:
                raise RuntimeError("connection refused")

        vault = _vault_mock()
        with patch.dict(sys.modules, {_VAULT_KEY: vault}):
            count = asyncio.run(backfill_missing_wallets(_make_pool(_BrokenConn())))
        assert count == 0, "backfill must return 0 on DB failure, not raise"

    def test_per_user_failure_does_not_abort_remaining(self):
        """If one user's wallet creation fails, the remaining users still get wallets."""
        uid_ok1 = uuid4()
        uid_fail = uuid4()
        uid_ok2 = uuid4()
        created: list[UUID] = []

        async def _sometimes_fail(user_id: UUID) -> None:
            if user_id == uid_fail:
                raise RuntimeError("key gen error")
            created.append(user_id)

        seed_mock = AsyncMock(return_value=True)
        vault = _vault_mock(_sometimes_fail)

        with (
            patch.dict(sys.modules, {_VAULT_KEY: vault}),
            patch.object(users_module, "seed_paper_capital", new=seed_mock),
        ):
            count = asyncio.run(
                backfill_missing_wallets(
                    _make_pool(_BackfillConn([uid_ok1, uid_fail, uid_ok2]))
                )
            )

        assert count == 2, f"Expected 2 successful, got {count}"
        assert uid_ok1 in created
        assert uid_ok2 in created
        assert uid_fail not in created
