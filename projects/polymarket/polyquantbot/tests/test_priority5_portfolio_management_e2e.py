"""Priority 5 — Portfolio Management Logic — End-to-End Tests.

Test IDs: PM-01 .. PM-25

Coverage:
  PM-01..PM-05  Portfolio domain model and schema validation
  PM-06..PM-10  Exposure aggregation
  PM-11..PM-15  Allocation logic (Kelly sizing)
  PM-16..PM-20  PnL logic and snapshot persistence
  PM-21..PM-25  Portfolio guardrails enforcement
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from projects.polymarket.polyquantbot.server.schemas.portfolio import (
    KELLY_FRACTION,
    MAX_CONCENTRATION_PCT,
    MAX_DRAWDOWN,
    MAX_POSITION_PCT,
    MAX_TOTAL_EXPOSURE_PCT,
    MIN_POSITION_USD,
    AllocationPlan,
    ExposureReport,
    GuardrailCheckResult,
    PortfolioOperationResult,
    PortfolioPosition,
    PortfolioSnapshot,
    PortfolioSummary,
    SignalAllocation,
    _new_snapshot_id,
)
from projects.polymarket.polyquantbot.server.services.portfolio_service import PortfolioService
from projects.polymarket.polyquantbot.server.storage.portfolio_store import PortfolioStore


# ── Helpers ───────────────────────────────────────────────────────────────────

def _utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _make_store(
    realized_pnl: float = 0.0,
    positions: list[PortfolioPosition] | None = None,
    per_market: dict[str, float] | None = None,
    insert_ok: bool = True,
    latest_snapshot: PortfolioSnapshot | None = None,
    list_snapshots: list[PortfolioSnapshot] | None = None,
) -> PortfolioStore:
    store = MagicMock(spec=PortfolioStore)
    store.get_realized_pnl = AsyncMock(return_value=realized_pnl)
    store.get_open_positions = AsyncMock(return_value=positions or [])
    store.get_exposure_per_market = AsyncMock(return_value=per_market or {})
    store.insert_snapshot = AsyncMock(return_value=insert_ok)
    store.get_latest_snapshot = AsyncMock(return_value=latest_snapshot)
    store.list_snapshots = AsyncMock(return_value=list_snapshots or [])
    return store


def _make_position(
    market_id: str = "mkt_A",
    side: str = "YES",
    size_usd: float = 100.0,
    entry_price: float = 0.5,
    unrealized_pnl: float = 5.0,
) -> PortfolioPosition:
    return PortfolioPosition(
        market_id=market_id,
        side=side,
        size_usd=size_usd,
        entry_price=entry_price,
        current_price=entry_price + 0.02,
        unrealized_pnl=unrealized_pnl,
        opened_at=1_000_000.0,
    )


# ── PM-01..PM-05: Domain model validation ────────────────────────────────────


def test_pm01_portfolio_position_frozen():
    """PM-01: PortfolioPosition is immutable."""
    pos = _make_position()
    with pytest.raises((AttributeError, TypeError)):
        pos.size_usd = 999.0  # type: ignore[misc]


def test_pm02_portfolio_summary_computed_fields():
    """PM-02: PortfolioSummary aggregates net_pnl correctly."""
    pos = _make_position(unrealized_pnl=20.0)
    summary = PortfolioSummary(
        tenant_id="t1",
        user_id="u1",
        wallet_id="w1",
        cash_usd=800.0,
        locked_usd=200.0,
        equity_usd=1000.0,
        realized_pnl=50.0,
        unrealized_pnl=20.0,
        net_pnl=70.0,
        drawdown=0.0,
        exposure_pct=0.2,
        position_count=1,
        positions=(pos,),
    )
    assert summary.net_pnl == 70.0
    assert summary.position_count == 1
    assert summary.computed_at is not None


def test_pm03_snapshot_id_prefix():
    """PM-03: Snapshot IDs are prefixed with 'pfs_'."""
    sid = _new_snapshot_id()
    assert sid.startswith("pfs_")
    assert len(sid) > 8


def test_pm04_portfolio_snapshot_frozen():
    """PM-04: PortfolioSnapshot is immutable."""
    snap = PortfolioSnapshot(
        snapshot_id="pfs_abc",
        tenant_id="t1",
        user_id="u1",
        wallet_id="w1",
        realized_pnl=10.0,
        unrealized_pnl=5.0,
        net_pnl=15.0,
        cash_usd=500.0,
        locked_usd=100.0,
        equity_usd=600.0,
        drawdown=0.01,
        exposure_pct=0.16,
        position_count=1,
        mode="paper",
        recorded_at=_utc(),
    )
    with pytest.raises((AttributeError, TypeError)):
        snap.net_pnl = 999.0  # type: ignore[misc]


def test_pm05_constants_locked():
    """PM-05: Risk constants match AGENTS.md hard rules."""
    assert KELLY_FRACTION == 0.25
    assert MAX_POSITION_PCT == 0.10
    assert MAX_TOTAL_EXPOSURE_PCT == 0.10
    assert MAX_DRAWDOWN == 0.08
    assert MIN_POSITION_USD == 10.0
    assert MAX_CONCENTRATION_PCT == 0.20


# ── PM-06..PM-10: Exposure aggregation ───────────────────────────────────────


@pytest.mark.asyncio
async def test_pm06_aggregate_exposure_single_market():
    """PM-06: Single market exposure computed correctly."""
    store = _make_store(per_market={"mkt_A": 200.0})
    svc = PortfolioService(store=store)
    report = await svc.aggregate_exposure("t1", "u1", equity_usd=1000.0)

    assert report.total_exposure_usd == 200.0
    assert abs(report.exposure_pct - 0.2) < 1e-6
    assert report.market_count == 1
    assert report.per_market["mkt_A"] == 200.0


@pytest.mark.asyncio
async def test_pm07_aggregate_exposure_multi_market():
    """PM-07: Multi-market exposure sums correctly."""
    store = _make_store(per_market={"mkt_A": 100.0, "mkt_B": 150.0})
    svc = PortfolioService(store=store)
    report = await svc.aggregate_exposure("t1", "u1", equity_usd=1000.0)

    assert report.total_exposure_usd == 250.0
    assert report.market_count == 2


@pytest.mark.asyncio
async def test_pm08_aggregate_exposure_empty():
    """PM-08: Zero exposure when no open positions."""
    store = _make_store(per_market={})
    svc = PortfolioService(store=store)
    report = await svc.aggregate_exposure("t1", "u1", equity_usd=1000.0)

    assert report.total_exposure_usd == 0.0
    assert report.exposure_pct == 0.0
    assert report.market_count == 0


@pytest.mark.asyncio
async def test_pm09_aggregate_exposure_zero_equity():
    """PM-09: Zero equity defaults to safe floor to avoid division by zero."""
    store = _make_store(per_market={"mkt_A": 100.0})
    svc = PortfolioService(store=store)
    report = await svc.aggregate_exposure("t1", "u1", equity_usd=0.0)
    # Should not raise; exposure_pct should reflect locked / 1.0
    assert report.total_exposure_usd == 100.0
    assert report.exposure_pct == pytest.approx(100.0, rel=1e-3)


@pytest.mark.asyncio
async def test_pm10_aggregate_exposure_db_error_returns_safe_default():
    """PM-10: DB error returns a zero ExposureReport, never raises."""
    store = MagicMock(spec=PortfolioStore)
    store.get_exposure_per_market = AsyncMock(side_effect=RuntimeError("db_down"))
    svc = PortfolioService(store=store)
    report = await svc.aggregate_exposure("t1", "u1", equity_usd=1000.0)

    assert report.total_exposure_usd == 0.0
    assert report.market_count == 0


# ── PM-11..PM-15: Allocation logic ───────────────────────────────────────────


def test_pm11_allocation_basic_kelly():
    """PM-11: Kelly allocation applies fractional formula correctly."""
    store = _make_store()
    svc = PortfolioService(store=store)
    signals = [{"signal_id": "s1", "market_id": "mkt_A", "edge": 0.1, "price": 0.5}]
    plan = svc.compute_allocation("u1", "w1", equity_usd=1000.0, signals=signals)

    # kelly_f = 0.1/0.5 = 0.2; size = 1000 * 0.25 * 0.2 = 50.0
    assert plan.allocations[0].size_usd == pytest.approx(50.0, rel=1e-3)
    assert plan.kelly_fraction == 0.25
    assert plan.total_bankroll == 1000.0


def test_pm12_allocation_max_position_cap():
    """PM-12: Allocation is capped at MAX_POSITION_PCT of equity."""
    store = _make_store()
    svc = PortfolioService(store=store)
    # Very high edge signal would exceed cap
    signals = [{"signal_id": "s1", "market_id": "mkt_A", "edge": 0.9, "price": 0.1}]
    plan = svc.compute_allocation("u1", "w1", equity_usd=1000.0, signals=signals)

    assert plan.allocations[0].size_usd <= 1000.0 * MAX_POSITION_PCT + 0.01


def test_pm13_allocation_below_floor_skipped():
    """PM-13: Signal whose Kelly size falls below MIN_POSITION_USD is skipped entirely."""
    store = _make_store()
    svc = PortfolioService(store=store)
    # edge=0.001, price=0.99 → size ≈ $0.25 (well below $10 floor) → skipped
    signals = [{"signal_id": "s1", "market_id": "mkt_A", "edge": 0.001, "price": 0.99}]
    plan = svc.compute_allocation("u1", "w1", equity_usd=1000.0, signals=signals)

    assert len(plan.allocations) == 0
    assert plan.total_allocated_usd == 0.0


def test_pm13b_allocation_negative_edge_skipped():
    """PM-13b: Signal with non-positive edge is always skipped."""
    store = _make_store()
    svc = PortfolioService(store=store)
    signals = [
        {"signal_id": "s1", "market_id": "mkt_A", "edge": 0.0, "price": 0.5},
        {"signal_id": "s2", "market_id": "mkt_B", "edge": -0.05, "price": 0.5},
    ]
    plan = svc.compute_allocation("u1", "w1", equity_usd=1000.0, signals=signals)

    assert len(plan.allocations) == 0


def test_pm14_allocation_multi_signal():
    """PM-14: Multi-signal allocation sums total correctly."""
    store = _make_store()
    svc = PortfolioService(store=store)
    signals = [
        {"signal_id": "s1", "market_id": "mkt_A", "edge": 0.1, "price": 0.5},
        {"signal_id": "s2", "market_id": "mkt_B", "edge": 0.08, "price": 0.4},
    ]
    plan = svc.compute_allocation("u1", "w1", equity_usd=1000.0, signals=signals)

    assert len(plan.allocations) == 2
    assert plan.total_allocated_usd == pytest.approx(
        sum(a.size_usd for a in plan.allocations), rel=1e-3
    )


def test_pm15_allocation_empty_signals():
    """PM-15: Empty signals produce a zero-allocation plan."""
    store = _make_store()
    svc = PortfolioService(store=store)
    plan = svc.compute_allocation("u1", "w1", equity_usd=1000.0, signals=[])

    assert len(plan.allocations) == 0
    assert plan.total_allocated_usd == 0.0


# ── PM-16..PM-20: PnL logic and snapshot ─────────────────────────────────────


@pytest.mark.asyncio
async def test_pm16_compute_summary_realized_pnl():
    """PM-16: Summary correctly reads realized PnL from DB."""
    store = _make_store(realized_pnl=123.45)
    svc = PortfolioService(store=store)
    result = await svc.compute_summary("t1", "u1", "w1", equity_usd=1000.0)

    assert result.outcome == "ok"
    assert result.summary is not None
    assert result.summary.realized_pnl == pytest.approx(123.45)


@pytest.mark.asyncio
async def test_pm17_compute_summary_unrealized_pnl():
    """PM-17: Summary sums unrealized PnL from open positions."""
    pos = _make_position(unrealized_pnl=30.0)
    store = _make_store(realized_pnl=50.0, positions=[pos])
    svc = PortfolioService(store=store)
    result = await svc.compute_summary("t1", "u1", "w1", equity_usd=1000.0)

    assert result.summary.unrealized_pnl == pytest.approx(30.0)
    assert result.summary.net_pnl == pytest.approx(80.0)


@pytest.mark.asyncio
async def test_pm18_compute_summary_drawdown():
    """PM-18: Drawdown computed correctly from peak equity."""
    store = _make_store()
    svc = PortfolioService(store=store)
    # peak = 1000, current = 900 → drawdown = 10%
    result = await svc.compute_summary(
        "t1", "u1", "w1",
        equity_usd=900.0,
        peak_equity=1000.0,
    )
    assert result.summary.drawdown == pytest.approx(0.1, rel=1e-3)


@pytest.mark.asyncio
async def test_pm19_record_snapshot_persists():
    """PM-19: record_snapshot inserts to DB and returns True."""
    pos = _make_position()
    summary = PortfolioSummary(
        tenant_id="t1", user_id="u1", wallet_id="w1",
        cash_usd=800.0, locked_usd=100.0, equity_usd=900.0,
        realized_pnl=50.0, unrealized_pnl=5.0, net_pnl=55.0,
        drawdown=0.01, exposure_pct=0.11, position_count=1,
        positions=(pos,),
    )
    store = _make_store(insert_ok=True)
    svc = PortfolioService(store=store)
    ok = await svc.record_snapshot(summary)

    assert ok is True
    store.insert_snapshot.assert_awaited_once()


@pytest.mark.asyncio
async def test_pm20_pnl_history_returns_snapshots():
    """PM-20: PnL history returns list of PortfolioSnapshot objects."""
    snap = PortfolioSnapshot(
        snapshot_id="pfs_x", tenant_id="t1", user_id="u1", wallet_id="w1",
        realized_pnl=10.0, unrealized_pnl=2.0, net_pnl=12.0,
        cash_usd=800.0, locked_usd=50.0, equity_usd=850.0,
        drawdown=0.0, exposure_pct=0.06, position_count=1,
        mode="PAPER", recorded_at=_utc(),
    )
    store = _make_store(list_snapshots=[snap])
    svc = PortfolioService(store=store)
    history = await svc.get_pnl_history("t1", "u1", "w1")

    assert len(history) == 1
    assert history[0].snapshot_id == "pfs_x"


# ── PM-21..PM-25: Portfolio guardrails ───────────────────────────────────────


def test_pm21_guardrails_pass_clean_state():
    """PM-21: Guardrails pass when all metrics are within limits."""
    store = _make_store()
    svc = PortfolioService(store=store)
    result = svc.check_guardrails(
        drawdown=0.02,
        exposure_pct=0.05,
        per_market_exposure={"mkt_A": 50.0},
        equity_usd=1000.0,
        kill_switch_active=False,
    )
    assert result.allowed is True
    assert len(result.violations) == 0


def test_pm22_guardrails_kill_switch_blocks():
    """PM-22: Kill switch always blocks regardless of other metrics."""
    store = _make_store()
    svc = PortfolioService(store=store)
    result = svc.check_guardrails(
        drawdown=0.0,
        exposure_pct=0.0,
        per_market_exposure={},
        equity_usd=1000.0,
        kill_switch_active=True,
    )
    assert result.allowed is False
    assert any("kill_switch" in v for v in result.violations)


def test_pm23_guardrails_drawdown_exceeded():
    """PM-23: Drawdown > 8% triggers violation."""
    store = _make_store()
    svc = PortfolioService(store=store)
    result = svc.check_guardrails(
        drawdown=0.09,  # over 8%
        exposure_pct=0.05,
        per_market_exposure={},
        equity_usd=1000.0,
        kill_switch_active=False,
    )
    assert result.allowed is False
    assert any("drawdown_exceeded" in v for v in result.violations)


def test_pm24_guardrails_exposure_cap_exceeded():
    """PM-24: Total exposure > MAX_TOTAL_EXPOSURE_PCT (10%) triggers violation."""
    store = _make_store()
    svc = PortfolioService(store=store)
    result = svc.check_guardrails(
        drawdown=0.01,
        exposure_pct=0.15,  # over 10% total exposure cap
        per_market_exposure={},
        equity_usd=1000.0,
        kill_switch_active=False,
    )
    assert result.allowed is False
    assert any("exposure_cap_exceeded" in v for v in result.violations)


def test_pm25_guardrails_concentration_exceeded():
    """PM-25: Single market > 20% of equity triggers concentration violation."""
    store = _make_store()
    svc = PortfolioService(store=store)
    # mkt_A has 250 USD locked of 1000 equity = 25% → over 20% cap
    result = svc.check_guardrails(
        drawdown=0.01,
        exposure_pct=0.25,
        per_market_exposure={"mkt_A": 250.0},
        equity_usd=1000.0,
        kill_switch_active=False,
    )
    assert result.allowed is False
    assert any("concentration_exceeded" in v for v in result.violations)


# ── PM-26..PM-28: Additional coverage for merge-blocker fixes ────────────────


@pytest.mark.asyncio
async def test_pm26_store_exposure_aggregates_duplicate_markets():
    """PM-26: PortfolioStore.get_exposure_per_market sums duplicate market_id rows."""
    from contextlib import asynccontextmanager
    from projects.polymarket.polyquantbot.server.storage.portfolio_store import PortfolioStore

    mock_rows = [
        {"market_id": "mkt_A", "size": 100.0},
        {"market_id": "mkt_A", "size": 150.0},
        {"market_id": "mkt_B", "size": 25.0},
    ]
    mock_conn = MagicMock()
    mock_conn.fetch = AsyncMock(return_value=mock_rows)

    @asynccontextmanager
    async def _acquire():
        yield mock_conn

    mock_pool = MagicMock()
    mock_pool.acquire = _acquire

    mock_db = MagicMock()
    mock_db._pool = mock_pool

    store = PortfolioStore(db=mock_db)
    result = await store.get_exposure_per_market(user_id="u1")

    assert result["mkt_A"] == pytest.approx(250.0)
    assert result["mkt_B"] == pytest.approx(25.0)
    assert len(result) == 2


def test_pm27_admin_route_forbidden_no_env_token(monkeypatch):
    """PM-27: /portfolio/admin returns 403 when PORTFOLIO_ADMIN_TOKEN env is absent."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from projects.polymarket.polyquantbot.server.api.portfolio_routes import build_portfolio_router

    monkeypatch.delenv("PORTFOLIO_ADMIN_TOKEN", raising=False)
    app = FastAPI()
    app.include_router(build_portfolio_router())
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/portfolio/admin")
    assert response.status_code == 403
    assert response.json()["status"] == "forbidden"


def test_pm28_admin_route_forbidden_wrong_token(monkeypatch):
    """PM-28: /portfolio/admin returns 403 when wrong token is supplied."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from projects.polymarket.polyquantbot.server.api.portfolio_routes import build_portfolio_router

    monkeypatch.setenv("PORTFOLIO_ADMIN_TOKEN", "correct_secret")
    app = FastAPI()
    app.include_router(build_portfolio_router())
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/portfolio/admin", headers={"X-Portfolio-Admin-Token": "wrong_token"})
    assert response.status_code == 403
    assert response.json()["status"] == "forbidden"
