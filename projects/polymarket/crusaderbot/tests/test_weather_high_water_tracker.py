"""Hermetic tests for the weather high-water tracker (activates Exit 2).

Wiring under test:
  * registry.bump_high_water_price — atomic JSONB merge that only ever raises
    positions.strategy_metadata['high_water_price']; ignores degenerate prices.
  * exit_watcher._act_on_decision — on a HELD weather tick, persists the live
    price as the running peak so the next tick's evaluate_exit (Exit 2 trailing
    stop) can read position.get("high_water_price").
  * Non-weather positions are NOT bumped (zero extra writes off the weather lane).

No DB, no broker, no network.
"""
from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from projects.polymarket.crusaderbot.domain.execution import exit_watcher
from projects.polymarket.crusaderbot.domain.positions import registry
from projects.polymarket.crusaderbot.domain.positions.registry import (
    OpenPositionForExit,
)


def _run(coro):
    return asyncio.run(coro)


def _make_position(**overrides) -> OpenPositionForExit:
    base = dict(
        id=uuid4(),
        user_id=uuid4(),
        telegram_user_id=12345,
        market_id="MKT-WX",
        market_question="High temp in NYC?",
        side="yes",
        entry_price=0.40,
        size_usdc=10.0,
        mode="paper",
        status="open",
        applied_tp_pct=0.20,
        applied_sl_pct=0.10,
        force_close_intent=False,
        close_failure_count=0,
        yes_price=0.40,
        no_price=0.60,
        market_resolved=False,
        resolution_at=datetime.now(timezone.utc) + timedelta(hours=12),
        risk_profile="balanced",
        strategy_type="weather",
    )
    base.update(overrides)
    return OpenPositionForExit(**base)


# ---------------------------------------------------------------------------
# registry.bump_high_water_price — guard + SQL shape
# ---------------------------------------------------------------------------


class _ExplodingPool:
    """A pool whose .acquire() must never be called in the guard path."""

    def acquire(self):  # pragma: no cover - asserted not reached
        raise AssertionError("bump_high_water_price acquired a connection for a degenerate price")


def _swap(obj, name, value):
    """Temporarily replace an attribute; returns a restore callable."""
    original = getattr(obj, name)
    setattr(obj, name, value)

    def restore():
        setattr(obj, name, original)

    return restore


def test_bump_high_water_ignores_none_price():
    restore = _swap(registry, "get_pool", lambda: _ExplodingPool())
    try:
        _run(registry.bump_high_water_price(uuid4(), uuid4(), None))  # type: ignore[arg-type]
    finally:
        restore()


def test_bump_high_water_ignores_zero_and_negative_price():
    restore = _swap(registry, "get_pool", lambda: _ExplodingPool())
    try:
        _run(registry.bump_high_water_price(uuid4(), uuid4(), 0.0))
        _run(registry.bump_high_water_price(uuid4(), uuid4(), -0.5))
    finally:
        restore()


class _CaptureConn:
    def __init__(self) -> None:
        self.executed: list[tuple] = []

    async def __aenter__(self) -> "_CaptureConn":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def execute(self, sql: str, *args) -> None:
        self.executed.append((sql, args))


class _CapturePool:
    def __init__(self, conn: _CaptureConn) -> None:
        self._conn = conn

    def acquire(self) -> _CaptureConn:
        return self._conn


def test_bump_high_water_executes_conditional_merge():
    conn = _CaptureConn()
    restore = _swap(registry, "get_pool", lambda: _CapturePool(conn))
    try:
        pid, uid = uuid4(), uuid4()
        _run(registry.bump_high_water_price(pid, uid, 0.55))
    finally:
        restore()
    assert len(conn.executed) == 1
    sql, args = conn.executed[0]
    # only-raises guard + JSONB merge that preserves the other metadata keys
    assert "high_water_price" in sql
    assert "jsonb_build_object" in sql
    assert "COALESCE(strategy_metadata, '{}'::jsonb)" in sql
    assert "$1::float8 > COALESCE(" in sql
    # price coerced to float and bound first; id/user follow
    assert args[0] == 0.55
    assert args[1] == pid
    assert args[2] == uid


# ---------------------------------------------------------------------------
# exit_watcher._act_on_decision — bump on held weather tick
# ---------------------------------------------------------------------------


def _patch_registry_calls():
    """Stub update_current_price + bump_high_water_price; capture invocations."""
    calls: dict[str, list] = {"update": [], "bump": []}

    async def fake_update(position_id, price, user_id, pnl_usdc=None):
        calls["update"].append((position_id, price, pnl_usdc))

    async def fake_bump(position_id, user_id, price):
        calls["bump"].append((position_id, user_id, price))

    restore_u = _swap(registry, "update_current_price", fake_update)
    restore_b = _swap(registry, "bump_high_water_price", fake_bump)

    def restore():
        restore_u()
        restore_b()

    return calls, restore


def test_act_on_decision_bumps_high_water_for_weather_hold():
    calls, restore = _patch_registry_calls()
    try:
        pos = _make_position(strategy_type="weather")
        dec = exit_watcher.ExitDecision(
            should_exit=False, reason=None, current_price=0.55
        )
        _run(exit_watcher._act_on_decision(pos, dec))
    finally:
        restore()
    assert len(calls["update"]) == 1
    assert len(calls["bump"]) == 1
    bumped_pid, bumped_uid, bumped_price = calls["bump"][0]
    assert bumped_pid == pos.id
    assert bumped_uid == pos.user_id
    assert bumped_price == 0.55


def test_act_on_decision_does_not_bump_for_non_weather():
    calls, restore = _patch_registry_calls()
    try:
        pos = _make_position(strategy_type="late_entry_v3")
        dec = exit_watcher.ExitDecision(
            should_exit=False, reason=None, current_price=0.55
        )
        _run(exit_watcher._act_on_decision(pos, dec))
    finally:
        restore()
    assert len(calls["update"]) == 1  # price still refreshed
    assert len(calls["bump"]) == 0  # but no high-water write


def test_act_on_decision_bump_failure_does_not_poison_hold():
    """A failing high-water bump must not raise out of the hold path."""
    calls: dict[str, list] = {"update": []}

    async def fake_update(position_id, price, user_id, pnl_usdc=None):
        calls["update"].append(price)

    async def boom_bump(position_id, user_id, price):
        raise RuntimeError("db gone")

    restore_u = _swap(registry, "update_current_price", fake_update)
    restore_b = _swap(registry, "bump_high_water_price", boom_bump)
    try:
        pos = _make_position(strategy_type="weather")
        dec = exit_watcher.ExitDecision(
            should_exit=False, reason=None, current_price=0.61
        )
        # Must NOT raise — the price refresh already committed.
        _run(exit_watcher._act_on_decision(pos, dec))
    finally:
        restore_u()
        restore_b()
    assert calls["update"] == [0.61]


# ---------------------------------------------------------------------------
# Source pin — the watcher only bumps on the held branch
# ---------------------------------------------------------------------------


def test_high_water_bump_is_gated_on_weather_in_watcher():
    src = inspect.getsource(exit_watcher._act_on_decision)
    assert 'position.strategy_type == "weather"' in src
    assert "bump_high_water_price" in src
