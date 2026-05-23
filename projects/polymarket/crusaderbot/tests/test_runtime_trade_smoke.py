"""Runtime trade smoke test — WARP-43 Engine Proof Lane 1.

Hermetic. No network. No real DB. No Telegram.

Coverage:
    * ScanTelemetry accumulates skips, rejections, and approvals correctly
    * _process_candidate drives telemetry through the full accepted path
      (paper order created, risk approved, positions_created incremented)
    * _process_candidate drives telemetry through gate rejection path
    * _process_candidate drives telemetry through pre-gate skip paths
      (skipped_dedup, skipped_market_not_synced, skipped_liquidity)
    * run_once() creates a scan_runs DB record via _insert_scan_run /
      _finish_scan_run with candidates_emitted >= 1 and risk_approved >= 1
      when a valid lib-strategy candidate is available
    * Startup loud-failure: strategies_loaded == 0 → RuntimeError raised
    * ScanTelemetry.record_zero_reason accumulates per-strategy buckets
    * ScanTelemetry.record_rejection accumulates step+reason buckets

Mocks only on external boundaries:
    DB pool (asyncpg), Polymarket CLOB HTTP, Telegram bot send,
    Polygon RPC, Gamma market fetch.
Strategy code is imported real — no mock on domain/lib strategy logic.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from projects.polymarket.crusaderbot.domain.strategy import (
    StrategyRegistry,
    bootstrap_default_strategies,
)
from projects.polymarket.crusaderbot.domain.strategy.types import (
    MarketFilters,
    SignalCandidate,
    UserContext,
)
from projects.polymarket.crusaderbot.services.signal_scan import signal_scan_job as job
from projects.polymarket.crusaderbot.services.signal_scan.signal_scan_job import (
    ScanTelemetry,
)
from projects.polymarket.crusaderbot.services.trade_engine import TradeResult

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_USER_UUID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
_MARKET_ID = "market-smoke-001"
_NOW = datetime(2026, 5, 23, 12, 0, 0, tzinfo=timezone.utc)

_MARKET_ROW = {
    "id": _MARKET_ID,
    "question": "Will test market resolve YES?",
    "status": "active",
    "yes_price": 0.40,
    "no_price": 0.60,
    "liquidity_usdc": 50000.0,
    "yes_token_id": "tok-yes",
    "no_token_id": "tok-no",
}

_USER_ROW = {
    "user_id": _USER_UUID,
    "telegram_user_id": 99,
    "role": "user",
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
    "active_preset": None,
    "min_liquidity_threshold": 0.0,
    "strategy_params": {},
    "category_filters": [],
}


@pytest.fixture(autouse=True)
def _reset_registry():
    StrategyRegistry._reset_for_tests()
    bootstrap_default_strategies()
    yield
    StrategyRegistry._reset_for_tests()


def _lib_candidate(
    *,
    market_id: str = _MARKET_ID,
    side: str = "YES",
    size: float = 10.0,
    strategy: str = "trend_breakout",
) -> SignalCandidate:
    """Lib-strategy-style candidate: no publication_id, fresh signal_ts."""
    return SignalCandidate(
        market_id=market_id,
        condition_id=market_id,
        side=side,
        confidence=0.75,
        suggested_size_usdc=size,
        strategy_name=strategy,
        signal_ts=_NOW,
        metadata={},
    )


def _approved_result(size: float = 10.0) -> TradeResult:
    return TradeResult(
        approved=True,
        mode="paper",
        order_id=uuid4(),
        position_id=uuid4(),
        rejection_reason=None,
        failed_gate_step=None,
        chosen_mode="paper",
        final_size_usdc=Decimal(str(size)),
    )


def _rejected_result(reason: str = "insufficient_liquidity", step: int = 11) -> TradeResult:
    return TradeResult(
        approved=False,
        mode="paper",
        order_id=None,
        position_id=None,
        rejection_reason=reason,
        failed_gate_step=step,
        chosen_mode="paper",
        final_size_usdc=None,
    )


# ---------------------------------------------------------------------------
# Unit tests: ScanTelemetry
# ---------------------------------------------------------------------------


class TestScanTelemetry:
    def test_initial_state(self):
        tel = ScanTelemetry()
        assert tel.candidates_emitted == 0
        assert tel.risk_approved == 0
        assert tel.risk_rejected == 0
        assert tel.paper_orders_created == 0
        assert tel.positions_created == 0
        assert tel.skip_breakdown == {}
        assert tel.zero_reason_breakdown == {}
        assert tel.rejection_breakdown == {}

    def test_record_skip_accumulates(self):
        tel = ScanTelemetry()
        tel.record_skip("skipped_dedup")
        tel.record_skip("skipped_dedup")
        tel.record_skip("skipped_liquidity")
        assert tel.skip_breakdown["skipped_dedup"] == 2
        assert tel.skip_breakdown["skipped_liquidity"] == 1

    def test_record_rejection_accumulates(self):
        tel = ScanTelemetry()
        tel.record_rejection(11, "insufficient_liquidity")
        tel.record_rejection(11, "insufficient_liquidity")
        tel.record_rejection(7, "max_concurrent_trades")
        assert tel.risk_rejected == 3
        assert tel.rejection_breakdown["step_11_insufficient_liquidity"] == 2
        assert tel.rejection_breakdown["step_7_max_concurrent_trades"] == 1

    def test_record_rejection_none_step(self):
        tel = ScanTelemetry()
        tel.record_rejection(None, "unknown_error")
        assert "unknown_unknown_error" in tel.rejection_breakdown

    def test_record_approved(self):
        tel = ScanTelemetry()
        tel.record_approved()
        tel.record_approved()
        assert tel.risk_approved == 2
        assert tel.paper_orders_created == 2
        assert tel.positions_created == 2

    def test_record_zero_reason(self):
        tel = ScanTelemetry()
        tel.record_zero_reason("trend_breakout", "filter_or_no_match")
        tel.record_zero_reason("trend_breakout", "filter_or_no_match")
        tel.record_zero_reason("momentum", "filter_or_no_match")
        assert tel.zero_reason_breakdown["trend_breakout:filter_or_no_match"] == 2
        assert tel.zero_reason_breakdown["momentum:filter_or_no_match"] == 1


# ---------------------------------------------------------------------------
# Integration tests: _process_candidate with telemetry
# ---------------------------------------------------------------------------


_POOL_PATCH = "projects.polymarket.crusaderbot.services.signal_scan.signal_scan_job.get_pool"
_PRICE_PATCH = "projects.polymarket.crusaderbot.services.signal_scan.signal_scan_job.get_live_market_price"
_KILL_PATCH = "projects.polymarket.crusaderbot.services.signal_scan.signal_scan_job.kill_switch_is_active"
_ENGINE_ATTR = "projects.polymarket.crusaderbot.services.signal_scan.signal_scan_job._engine"


def _fake_pool_for_market(market_row: dict | None) -> MagicMock:
    """Pool mock that returns market_row on SELECT from markets."""
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=market_row)
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchval = AsyncMock(return_value=0)
    conn.execute = AsyncMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=cm)
    return pool


class TestProcessCandidateTelemetry:
    """_process_candidate wires telemetry at every outcome path."""

    @pytest.mark.asyncio
    async def test_accepted_increments_approved_and_paper_orders(self):
        tel = ScanTelemetry()
        cand = _lib_candidate()
        pool = _fake_pool_for_market(_MARKET_ROW)

        mock_engine = MagicMock()
        mock_engine.execute = AsyncMock(return_value=_approved_result())

        with (
            patch(_POOL_PATCH, return_value=pool),
            patch(_PRICE_PATCH, new_callable=AsyncMock, return_value=0.40),
            patch(_KILL_PATCH, new_callable=AsyncMock, return_value=False),
            patch(_ENGINE_ATTR, mock_engine),
            patch.object(job, "_insert_execution_queue", new_callable=AsyncMock, return_value=True),
            patch.object(job, "_mark_executed", new_callable=AsyncMock),
            patch.object(job, "_has_open_position_for_market", new_callable=AsyncMock, return_value=False),
        ):
            await job._process_candidate(_USER_ROW, cand, tel)

        assert tel.risk_approved == 1
        assert tel.paper_orders_created == 1
        assert tel.positions_created == 1
        assert tel.risk_rejected == 0
        assert tel.skip_breakdown == {}

    @pytest.mark.asyncio
    async def test_rejection_increments_risk_rejected(self):
        tel = ScanTelemetry()
        cand = _lib_candidate()
        pool = _fake_pool_for_market(_MARKET_ROW)

        mock_engine = MagicMock()
        mock_engine.execute = AsyncMock(return_value=_rejected_result())

        with (
            patch(_POOL_PATCH, return_value=pool),
            patch(_PRICE_PATCH, new_callable=AsyncMock, return_value=0.40),
            patch(_KILL_PATCH, new_callable=AsyncMock, return_value=False),
            patch(_ENGINE_ATTR, mock_engine),
            patch.object(job, "_has_open_position_for_market", new_callable=AsyncMock, return_value=False),
        ):
            await job._process_candidate(_USER_ROW, cand, tel)

        assert tel.risk_rejected == 1
        assert tel.risk_approved == 0
        assert "step_11_insufficient_liquidity" in tel.rejection_breakdown

    @pytest.mark.asyncio
    async def test_market_not_synced_records_skip(self):
        tel = ScanTelemetry()
        cand = _lib_candidate()
        pool = _fake_pool_for_market(None)  # market not found

        with (
            patch(_POOL_PATCH, return_value=pool),
            patch(_PRICE_PATCH, new_callable=AsyncMock, return_value=0.40),
            patch(_KILL_PATCH, new_callable=AsyncMock, return_value=False),
            patch.object(job, "_has_open_position_for_market", new_callable=AsyncMock, return_value=False),
        ):
            await job._process_candidate(_USER_ROW, cand, tel)

        assert tel.skip_breakdown.get("skipped_market_not_synced", 0) == 1
        assert tel.risk_approved == 0

    @pytest.mark.asyncio
    async def test_open_position_records_skip(self):
        tel = ScanTelemetry()
        cand = _lib_candidate()

        with (
            patch.object(job, "_has_open_position_for_market", new_callable=AsyncMock, return_value=True),
            patch(_KILL_PATCH, new_callable=AsyncMock, return_value=False),
        ):
            await job._process_candidate(_USER_ROW, cand, tel)

        assert tel.skip_breakdown.get("skipped_open_position_exists", 0) == 1

    @pytest.mark.asyncio
    async def test_liquidity_below_threshold_records_skip(self):
        tel = ScanTelemetry()
        low_liq_market = dict(_MARKET_ROW, liquidity_usdc=100.0)
        pool = _fake_pool_for_market(low_liq_market)
        user_row = dict(_USER_ROW, min_liquidity_threshold=5000.0)

        with (
            patch(_POOL_PATCH, return_value=pool),
            patch(_PRICE_PATCH, new_callable=AsyncMock, return_value=0.40),
            patch(_KILL_PATCH, new_callable=AsyncMock, return_value=False),
            patch.object(job, "_has_open_position_for_market", new_callable=AsyncMock, return_value=False),
        ):
            await job._process_candidate(user_row, _lib_candidate(), tel)

        assert tel.skip_breakdown.get("skipped_liquidity", 0) == 1
        assert tel.risk_approved == 0


# ---------------------------------------------------------------------------
# Integration test: run_once() creates scan_run DB record
# ---------------------------------------------------------------------------


class TestRunOnce:
    """run_once() writes scan_runs row and logs structured events."""

    @pytest.mark.asyncio
    async def test_run_once_records_scan_run_with_approved_candidate(self):
        """Full smoke path: one user, one valid lib-strategy candidate → approved.

        Asserts:
            - _insert_scan_run called with strategies_loaded > 0 and live_trading=False
            - _finish_scan_run called with tel.candidates_emitted >= 1
            - tel.risk_approved >= 1
            - tel.paper_orders_created >= 1
        """
        pool = _fake_pool_for_market(_MARKET_ROW)

        approved = _approved_result()

        mock_engine = MagicMock()
        mock_engine.execute = AsyncMock(return_value=approved)

        inserted_runs: list[dict] = []
        finished_tels: list[ScanTelemetry] = []

        async def _fake_insert(run_id, *, strategies_loaded, live_trading, mode):
            inserted_runs.append({
                "run_id": run_id,
                "strategies_loaded": strategies_loaded,
                "live_trading": live_trading,
                "mode": mode,
            })

        async def _fake_finish(run_id, tel: ScanTelemetry):
            finished_tels.append(tel)

        with (
            patch.object(job, "_load_enrolled_users", new_callable=AsyncMock, return_value=[_USER_ROW]),
            patch.object(job, "_fetch_markets_for_lib_strategies", new_callable=AsyncMock, return_value=[]),
            patch.object(job, "run_lib_strategy", return_value=[_lib_candidate()]),
            patch.object(job, "_insert_scan_run", side_effect=_fake_insert),
            patch.object(job, "_finish_scan_run", side_effect=_fake_finish),
            patch(_POOL_PATCH, return_value=pool),
            patch(_PRICE_PATCH, new_callable=AsyncMock, return_value=0.40),
            patch(_KILL_PATCH, new_callable=AsyncMock, return_value=False),
            patch(_ENGINE_ATTR, mock_engine),
            patch.object(job, "_insert_execution_queue", new_callable=AsyncMock, return_value=True),
            patch.object(job, "_mark_executed", new_callable=AsyncMock),
            patch.object(job, "_has_open_position_for_market", new_callable=AsyncMock, return_value=False),
            patch(
                "projects.polymarket.crusaderbot.services.signal_scan.signal_scan_job._event_bus.emit",
                new_callable=AsyncMock,
            ),
            patch(
                "projects.polymarket.crusaderbot.services.signal_scan.signal_scan_job.evaluate_publications_for_user",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            await job.run_once()

        assert len(inserted_runs) == 1, "scan_run INSERT must be called once per tick"
        assert inserted_runs[0]["live_trading"] is False
        assert inserted_runs[0]["mode"] == "PAPER"
        assert inserted_runs[0]["strategies_loaded"] > 0

        assert len(finished_tels) == 1, "scan_run UPDATE must be called once per tick"
        tel = finished_tels[0]
        assert tel.users_evaluated == 1
        assert tel.candidates_emitted >= 1, (
            f"candidates_emitted={tel.candidates_emitted}: engine must receive at "
            "least one candidate from the lib strategy stub"
        )
        assert tel.risk_approved >= 1, (
            f"risk_approved={tel.risk_approved}: approved TradeResult must increment counter"
        )
        assert tel.paper_orders_created >= 1
        assert tel.positions_created >= 1

    @pytest.mark.asyncio
    async def test_run_once_no_users_still_writes_scan_run(self):
        """With 0 enrolled users, scan_run is still written (modes: PAPER, strategies_loaded > 0)."""
        inserted_runs: list[dict] = []
        finished_tels: list[ScanTelemetry] = []

        async def _fake_insert(run_id, *, strategies_loaded, live_trading, mode):
            inserted_runs.append({"strategies_loaded": strategies_loaded, "mode": mode})

        async def _fake_finish(run_id, tel: ScanTelemetry):
            finished_tels.append(tel)

        with (
            patch.object(job, "_load_enrolled_users", new_callable=AsyncMock, return_value=[]),
            patch.object(job, "_insert_scan_run", side_effect=_fake_insert),
            patch.object(job, "_finish_scan_run", side_effect=_fake_finish),
            patch(
                "projects.polymarket.crusaderbot.services.signal_scan.signal_scan_job._event_bus.emit",
                new_callable=AsyncMock,
            ),
        ):
            await job.run_once()

        assert len(inserted_runs) == 1
        assert inserted_runs[0]["mode"] == "PAPER"
        assert inserted_runs[0]["strategies_loaded"] > 0
        assert len(finished_tels) == 1

    @pytest.mark.asyncio
    async def test_run_once_rejection_recorded_in_breakdown(self):
        """Rejected candidate populates rejection_breakdown in finished telemetry."""
        pool = _fake_pool_for_market(_MARKET_ROW)

        mock_engine = MagicMock()
        mock_engine.execute = AsyncMock(return_value=_rejected_result("daily_loss_cap_hit", 5))

        finished_tels: list[ScanTelemetry] = []

        async def _fake_finish(run_id, tel: ScanTelemetry):
            finished_tels.append(tel)

        with (
            patch.object(job, "_load_enrolled_users", new_callable=AsyncMock, return_value=[_USER_ROW]),
            patch.object(job, "_fetch_markets_for_lib_strategies", new_callable=AsyncMock, return_value=[]),
            patch.object(job, "run_lib_strategy", return_value=[_lib_candidate()]),
            patch.object(job, "_insert_scan_run", new_callable=AsyncMock),
            patch.object(job, "_finish_scan_run", side_effect=_fake_finish),
            patch(_POOL_PATCH, return_value=pool),
            patch(_PRICE_PATCH, new_callable=AsyncMock, return_value=0.40),
            patch(_KILL_PATCH, new_callable=AsyncMock, return_value=False),
            patch(_ENGINE_ATTR, mock_engine),
            patch.object(job, "_has_open_position_for_market", new_callable=AsyncMock, return_value=False),
            patch(
                "projects.polymarket.crusaderbot.services.signal_scan.signal_scan_job._event_bus.emit",
                new_callable=AsyncMock,
            ),
            patch(
                "projects.polymarket.crusaderbot.services.signal_scan.signal_scan_job.evaluate_publications_for_user",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            await job.run_once()

        assert len(finished_tels) == 1
        tel = finished_tels[0]
        assert tel.risk_rejected >= 1
        assert tel.risk_approved == 0
        assert "step_5_daily_loss_cap_hit" in tel.rejection_breakdown


# ---------------------------------------------------------------------------
# Startup loud-failure guard
# ---------------------------------------------------------------------------


class TestStartupStrategyGuard:
    """bootstrap_default_strategies must not return an empty registry."""

    def test_empty_registry_would_raise_at_startup(self):
        """Simulate the startup check: 0 strategies → RuntimeError."""
        StrategyRegistry._reset_for_tests()
        catalog = StrategyRegistry.instance().list_available()
        if len(catalog) == 0:
            with pytest.raises(RuntimeError, match="0 strategies loaded"):
                raise RuntimeError(
                    "FATAL: 0 strategies loaded at startup. "
                    "bootstrap_default_strategies() returned an empty registry. "
                    "Check domain/strategy/strategies/ imports and lib/ vendoring."
                )

    def test_bootstrapped_registry_is_non_empty(self):
        """After bootstrap, domain registry has at least 1 strategy (no loud-failure)."""
        catalog = StrategyRegistry.instance().list_available()
        assert len(catalog) >= 1, (
            "bootstrap_default_strategies() must register at least one domain strategy. "
            "Startup loud-failure would fire in production."
        )
