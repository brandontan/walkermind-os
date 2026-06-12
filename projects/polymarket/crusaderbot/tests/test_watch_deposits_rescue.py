"""Deposit-watcher rescue lane (WARP/root-deposit-watcher-rescue).

Pins the three fixes from the prod incident where the deposit watcher never
completed one tick (chain_cursor stuck at its migration-seeded 0 since
2026-05-05 while every failing tick logged an invisible WARNING):

1. Consecutive RPC-failure streaks escalate to ERROR (-> Sentry) at the 3rd
   failure and re-fire periodically — an outage can no longer hide at
   warning level. A successful tick resets the streak.
2. The cold-start scan lookback is config-driven
   (``DEPOSIT_SCAN_LOOKBACK_BLOCKS``) and threaded into
   ``polygon.scan_from_cursor`` — a recovered watcher re-finds deposits sent
   during the outage instead of silently skipping anything older than the
   old hardcoded 2000 blocks (~70 min on Polygon).
3. The open-position market dedup in ``_process_candidate`` FAILS CLOSED on
   a DB error: gate step 10 dedups on the (market, side, price, size)
   idempotency key, so it is NOT a safety net against a second same-market
   position at a different price.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from projects.polymarket.crusaderbot import config as crusaderbot_config
from projects.polymarket.crusaderbot import scheduler
from projects.polymarket.crusaderbot.domain.strategy import (
    StrategyRegistry,
    bootstrap_default_strategies,
)
from projects.polymarket.crusaderbot.domain.strategy.types import SignalCandidate
from projects.polymarket.crusaderbot.services.signal_scan import (
    signal_scan_job as ssj,
)
from projects.polymarket.crusaderbot.services.trade_engine import TradeResult


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("OPERATOR_CHAT_ID", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("WALLET_HD_SEED", "seed")
    monkeypatch.setenv("WALLET_ENCRYPTION_KEY", "k")
    monkeypatch.setenv("POLYGON_RPC_URL", "https://rpc")
    monkeypatch.setenv("ALCHEMY_POLYGON_WS_URL", "wss://ws")


@pytest.fixture(autouse=True)
def _isolated_state():
    StrategyRegistry._reset_for_tests()
    crusaderbot_config.get_settings.cache_clear()
    scheduler._watch_deposits_fail_streak = 0
    yield
    StrategyRegistry._reset_for_tests()
    crusaderbot_config.get_settings.cache_clear()
    scheduler._watch_deposits_fail_streak = 0


# ---------------------------------------------------------------------
# 1. Failure-streak escalation
# ---------------------------------------------------------------------


def test_streak_escalates_to_error_on_third_consecutive_failure():
    fake_log = MagicMock()
    with patch.object(scheduler, "log", fake_log):
        scheduler._watch_deposits_failed("head read", RuntimeError("rpc down"))
        scheduler._watch_deposits_failed("head read", RuntimeError("rpc down"))
        assert fake_log.warning.call_count == 2
        assert fake_log.error.call_count == 0
        scheduler._watch_deposits_failed("head read", RuntimeError("rpc down"))
        assert fake_log.error.call_count == 1
    kwargs = fake_log.error.call_args.kwargs
    assert kwargs["streak"] == 3
    assert "rpc down" in kwargs["err"]


def test_streak_refires_error_periodically_not_every_tick():
    fake_log = MagicMock()
    with patch.object(scheduler, "log", fake_log):
        for _ in range(33):  # escalate at 3, refire at 3 + 30
            scheduler._watch_deposits_failed("scan", RuntimeError("boom"))
    assert fake_log.error.call_count == 2
    streaks = [c.kwargs["streak"] for c in fake_log.error.call_args_list]
    assert streaks == [3, 33]


# ---------------------------------------------------------------------
# 2. watch_deposits: success resets streak + lookback threaded
# ---------------------------------------------------------------------


class _FakeSettings:
    DEPOSIT_CONFIRMATION_DEPTH = 32
    WRONG_TOKEN_ALERTS_ENABLED = False
    DEPOSIT_SCAN_LOOKBACK_BLOCKS = 77_777


class _Txn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return None


class _WatcherConn:
    def transaction(self):
        return _Txn()

    async def fetch(self, sql: str, *args):
        if "FROM wallets" in sql:
            return [{
                "user_id": uuid4(),
                "deposit_address": "0x" + "11" * 20,
                "safe_address": None,
                "polymarket_deposit_wallet": None,
            }]
        if "status='pending'" in sql:
            return []
        raise AssertionError(f"unexpected fetch: {sql}")

    async def fetchval(self, sql: str, *args):
        if "block_number FROM chain_cursor" in sql:
            return 0
        raise AssertionError(f"unexpected fetchval: {sql}")

    async def execute(self, sql: str, *args):
        return "INSERT 0 1"


class _WatcherPool:
    def acquire(self):
        conn = _WatcherConn()

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *_a):
                return None

        return _Ctx()


def test_successful_tick_resets_streak_and_threads_lookback():
    scheduler._watch_deposits_fail_streak = 7  # mid-outage
    scan = AsyncMock(return_value=([], 900))
    from types import SimpleNamespace as _NS
    _asset = _NS(token_symbol="USDC.e", token_contract="0x" + "27" * 20,
                 network="Polygon", chain_id=137, decimals=6)
    with patch.object(scheduler, "get_settings", return_value=_FakeSettings()), \
            patch.object(scheduler, "get_pool", return_value=_WatcherPool()), \
            patch.object(scheduler, "primary_deposit_asset", lambda: _asset), \
            patch.object(scheduler.polygon, "latest_block",
                         new=AsyncMock(return_value=1_000)), \
            patch.object(scheduler.polygon, "scan_from_cursor", new=scan):
        asyncio.run(scheduler.watch_deposits())
    assert scheduler._watch_deposits_fail_streak == 0
    assert scan.call_args.kwargs["lookback"] == 77_777


def test_failed_tick_increments_streak():
    with patch.object(scheduler, "get_settings", return_value=_FakeSettings()), \
            patch.object(scheduler, "get_pool", return_value=_WatcherPool()), \
            patch.object(scheduler.polygon, "latest_block",
                         new=AsyncMock(side_effect=RuntimeError("rpc down"))):
        asyncio.run(scheduler.watch_deposits())
    assert scheduler._watch_deposits_fail_streak == 1


def test_config_default_lookback(monkeypatch: pytest.MonkeyPatch):
    _set_required_env(monkeypatch)
    monkeypatch.delenv("DEPOSIT_SCAN_LOOKBACK_BLOCKS", raising=False)
    s = crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert s.DEPOSIT_SCAN_LOOKBACK_BLOCKS == 50_000


# ---------------------------------------------------------------------
# 3. Open-position dedup fails CLOSED on DB error
# ---------------------------------------------------------------------


_USER_UUID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


def _user_row() -> dict:
    return {
        "user_id": _USER_UUID,
        "telegram_user_id": 42,
        "auto_trade_on": True,
        "paused": False,
        "balance_usdc": 500.0,
        "risk_profile": "balanced",
        "trading_mode": "paper",
        "tp_pct": 0.20,
        "sl_pct": 0.08,
        "daily_loss_override": None,
        "capital_allocation_pct": 0.10,
        "sub_account_id": uuid4(),
        "resolved_profile": "balanced",
        "active_preset": "safe_close",
    }


def _market_row() -> dict:
    return {
        "id": "market-001",
        "slug": "btc-no-updown-test",
        "question": "Will X happen?",
        "status": "active",
        "yes_price": 0.55,
        "no_price": 0.45,
        "yes_token_id": "tok_yes",
        "no_token_id": "tok_no",
        "liquidity_usdc": 20000.0,
    }


def _candidate() -> SignalCandidate:
    return SignalCandidate(
        market_id="market-001",
        condition_id="market-001",
        side="YES",
        confidence=0.7,
        suggested_size_usdc=10.0,
        strategy_name="late_entry_v3",
        signal_ts=datetime.now(timezone.utc),
        metadata={
            "market_id": "market-001",
            "entry_price": 0.65,
            "fav_price_min": 0.60,
            "fav_price_max": 0.70,
            "underdog_mode": False,
        },
    )


def _approved_result() -> TradeResult:
    return TradeResult(
        approved=True,
        mode="paper",
        order_id=uuid4(),
        position_id=uuid4(),
        rejection_reason=None,
        failed_gate_step=None,
        chosen_mode="paper",
        final_size_usdc=Decimal("10"),
    )


def _drive(*, dedup_behavior) -> bool:
    """Drive _process_candidate; return True iff the engine was reached."""
    engine_called = {"called": False}

    async def _track_execute(signal):
        engine_called["called"] = True
        return _approved_result()

    with patch.object(ssj, "_load_stale_queued_row", return_value=None), \
            patch.object(ssj, "_publication_already_queued", return_value=False), \
            patch.object(ssj, "_has_open_position_for_market",
                         new=AsyncMock(**dedup_behavior)), \
            patch.object(ssj, "_load_market", return_value=_market_row()), \
            patch.object(ssj, "get_live_market_price",
                         new=AsyncMock(return_value=0.66)), \
            patch.object(ssj._engine, "execute", side_effect=_track_execute), \
            patch.object(ssj, "_insert_execution_queue", return_value=True), \
            patch.object(ssj, "_mark_executed", new=AsyncMock()):
        asyncio.run(ssj._process_candidate(_user_row(), _candidate()))
    return engine_called["called"]


def test_dedup_db_error_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A DB error in the open-position dedup check must SKIP the candidate,
    never fall through to execution (the pre-fix behavior)."""
    _set_required_env(monkeypatch)
    bootstrap_default_strategies()
    reached = _drive(dedup_behavior={"side_effect": RuntimeError("pool wedged")})
    assert not reached, (
        "dedup check failure must fail CLOSED — candidate skipped, engine "
        "never reached"
    )


def test_dedup_healthy_path_still_executes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Positive control: with the dedup check healthy and returning False,
    the same candidate reaches the engine — proving the fail-closed test
    blocks on the error path, not on an unrelated gate."""
    _set_required_env(monkeypatch)
    bootstrap_default_strategies()
    reached = _drive(dedup_behavior={"return_value": False})
    assert reached, "healthy dedup path must still reach the engine"
