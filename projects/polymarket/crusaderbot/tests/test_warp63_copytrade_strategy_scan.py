"""Hermetic tests for WARP-63: CopyTradeStrategy.scan() reads copy_trade_tasks.

No DB, no network. Pool is mocked via unittest.mock.patch so the strategy
can be exercised against controlled row fixtures without Postgres.
"""
from __future__ import annotations

import asyncio
import pathlib
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

# Resolve the source file path relative to this test file, not CWD,
# so the tests work regardless of whether pytest is invoked from the
# repo root or from within projects/polymarket/crusaderbot/.
_SRC = pathlib.Path(__file__).resolve().parent.parent / "domain/signal/copy_trade.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pool(fetch_rows: list[dict]) -> MagicMock:
    """Return a mock asyncpg pool whose acquire().__aenter__ yields a conn
    that returns fetch_rows (plain dicts, [] subscriptable) on conn.fetch()."""
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=list(fetch_rows))
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=cm)
    return pool


_USER = {"id": "user-uuid-1", "balance_usdc": 1000.0}
_SETTINGS = {"capital_alloc_pct": 0.5}


# ---------------------------------------------------------------------------
# Source-level assertions (no import needed)
# ---------------------------------------------------------------------------

def test_copy_targets_not_referenced_in_source():
    src = _SRC.read_text()
    assert "copy_targets" not in src, "copy_targets still referenced in domain/signal/copy_trade.py"


def test_copy_trade_tasks_referenced_in_source():
    src = _SRC.read_text()
    assert "copy_trade_tasks" in src


def test_wallet_address_column_used():
    src = _SRC.read_text()
    assert "wallet_address" in src
    assert "target_wallet_address" not in src


def test_copy_amount_column_used():
    src = _SRC.read_text()
    assert "copy_amount" in src
    assert "scale_factor" not in src


def test_last_seen_tx_not_referenced():
    src = _SRC.read_text()
    assert "last_seen_tx" not in src


# ---------------------------------------------------------------------------
# Behavioural tests (mock pool + mock get_user_activity)
# ---------------------------------------------------------------------------

def test_scan_returns_empty_when_no_active_tasks():
    from projects.polymarket.crusaderbot.domain.signal.copy_trade import CopyTradeStrategy

    pool = _make_pool([])
    strat = CopyTradeStrategy()
    with patch(
        "projects.polymarket.crusaderbot.domain.signal.copy_trade.get_pool",
        return_value=pool,
    ):
        result = asyncio.run(strat.scan(_USER, _SETTINGS))
    assert result == []


def test_scan_skips_trade_with_zero_size():
    """size_raw=0 → skipped before SignalCandidate construction."""
    from projects.polymarket.crusaderbot.domain.signal.copy_trade import CopyTradeStrategy

    task_row = {"id": "task-1", "wallet_address": "0xLeader", "copy_amount": Decimal("10")}
    pool = _make_pool([task_row])
    trades = [{"market": "mkt-C", "outcome": "yes", "size": 0, "price": 0.5,
               "transactionHash": "0xTX3"}]

    strat = CopyTradeStrategy()
    with patch(
        "projects.polymarket.crusaderbot.domain.signal.copy_trade.get_pool",
        return_value=pool,
    ), patch(
        "projects.polymarket.crusaderbot.domain.signal.copy_trade.get_user_activity",
        new=AsyncMock(return_value=trades),
    ):
        result = asyncio.run(strat.scan(_USER, _SETTINGS))

    assert result == []


def test_scan_skips_wallet_fetch_error_and_continues():
    """Error on wallet A → logged, wallet B proceeds (empty trades → no signals)."""
    from projects.polymarket.crusaderbot.domain.signal.copy_trade import CopyTradeStrategy

    task_rows = [
        {"id": "task-1", "wallet_address": "0xBad", "copy_amount": Decimal("10")},
        {"id": "task-2", "wallet_address": "0xGood", "copy_amount": Decimal("10")},
    ]
    pool = _make_pool(task_rows)

    async def _activity(wallet, limit=10):
        if wallet == "0xBad":
            raise RuntimeError("timeout")
        return []

    strat = CopyTradeStrategy()
    with patch(
        "projects.polymarket.crusaderbot.domain.signal.copy_trade.get_pool",
        return_value=pool,
    ), patch(
        "projects.polymarket.crusaderbot.domain.signal.copy_trade.get_user_activity",
        new=_activity,
    ):
        result = asyncio.run(strat.scan(_USER, _SETTINGS))

    assert result == []


def test_scan_sql_targets_copy_trade_tasks_for_user():
    """SQL sent to conn.fetch must target copy_trade_tasks with user_id param."""
    from projects.polymarket.crusaderbot.domain.signal.copy_trade import CopyTradeStrategy

    pool = _make_pool([])
    conn = pool.acquire().__aenter__.return_value

    strat = CopyTradeStrategy()
    with patch(
        "projects.polymarket.crusaderbot.domain.signal.copy_trade.get_pool",
        return_value=pool,
    ), patch(
        "projects.polymarket.crusaderbot.domain.signal.copy_trade.get_user_activity",
        new=AsyncMock(return_value=[]),
    ):
        asyncio.run(strat.scan(_USER, _SETTINGS))

    call_args = conn.fetch.call_args
    sql = call_args[0][0]
    assert "copy_trade_tasks" in sql, "SQL must query copy_trade_tasks"
    assert "copy_targets" not in sql, "SQL must not query copy_targets"
    assert call_args[0][1] == _USER["id"], "user_id must be passed as SQL param"
