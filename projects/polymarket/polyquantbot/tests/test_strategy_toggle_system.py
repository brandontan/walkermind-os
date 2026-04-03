"""Strategy Toggle System — Unit Test Suite.

Validates the strategy toggle system end-to-end:

  ── StrategyStateManager ──
  ST-01  Default state has all strategies enabled
  ST-02  toggle() flips a strategy from enabled to disabled
  ST-03  toggle() flips a strategy from disabled to enabled
  ST-04  toggle() raises ValueError for unknown strategy names
  ST-05  get_active() returns only enabled strategies
  ST-06  get_state() returns full dict copy
  ST-07  is_active() returns correct bool for known strategy
  ST-08  is_active() returns False for unknown strategy
  ST-09  Disabling last strategy auto-enables all (failsafe)
  ST-10  load() uses DB data when db provided and non-empty
  ST-11  load() falls back to Redis when DB returns empty
  ST-12  load() uses in-memory defaults when neither backend provides data
  ST-13  load() falls back to defaults when DB raises error
  ST-14  save() writes to DB when db provided
  ST-15  save() writes to Redis when redis provided
  ST-16  save() returns False when neither backend provided
  ST-17  save() returns True if at least one backend succeeds

  ── DatabaseClient strategy_state methods ──
  ST-18  load_strategy_state() returns empty dict when no rows
  ST-19  save_strategy_state() returns True with empty state dict

  ── signal_engine.generate_signals() strategy guard ──
  ST-20  Empty strategy_state (all False) → returns [] + logs warning
  ST-21  strategy_state=None → signals generated normally
  ST-22  At least one active strategy → signals generated normally
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from projects.polymarket.polyquantbot.strategy.strategy_manager import (
    StrategyStateManager,
    KNOWN_STRATEGIES,
)
from projects.polymarket.polyquantbot.core.signal.signal_engine import generate_signals


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_manager(**kwargs: bool) -> StrategyStateManager:
    """Create a StrategyStateManager with optional initial state overrides."""
    if kwargs:
        return StrategyStateManager(initial_state=kwargs)
    return StrategyStateManager()


def _market(
    p_market: float = 0.40,
    p_model: float = 0.70,
    liquidity_usd: float = 50_000.0,
) -> dict:
    return {
        "market_id": "mkt-test",
        "p_market": p_market,
        "p_model": p_model,
        "liquidity_usd": liquidity_usd,
    }


# ══════════════════════════════════════════════════════════════════════════════
# ST-01 — ST-09: StrategyStateManager core behaviour
# ══════════════════════════════════════════════════════════════════════════════


class TestSTManagerCore:
    """Core StrategyStateManager state machine tests."""

    def test_st01_default_state_all_enabled(self) -> None:
        """ST-01: All known strategies start enabled."""
        mgr = _make_manager()
        for s in KNOWN_STRATEGIES:
            assert mgr.is_active(s) is True, f"Expected {s!r} to be active by default"

    def test_st02_toggle_enabled_to_disabled(self) -> None:
        """ST-02: Toggling an enabled strategy disables it."""
        mgr = _make_manager()
        result = mgr.toggle("ev_momentum")
        assert result is False
        assert mgr.is_active("ev_momentum") is False

    def test_st03_toggle_disabled_to_enabled(self) -> None:
        """ST-03: Toggling a disabled strategy enables it."""
        mgr = _make_manager(ev_momentum=False)
        result = mgr.toggle("ev_momentum")
        assert result is True
        assert mgr.is_active("ev_momentum") is True

    def test_st04_toggle_unknown_raises(self) -> None:
        """ST-04: Toggling an unknown strategy name raises ValueError."""
        mgr = _make_manager()
        with pytest.raises(ValueError, match="Unknown strategy"):
            mgr.toggle("nonexistent_strategy")

    def test_st05_get_active_returns_enabled_only(self) -> None:
        """ST-05: get_active() returns only enabled strategy names."""
        mgr = _make_manager(ev_momentum=False)
        active = mgr.get_active()
        assert "ev_momentum" not in active
        assert "mean_reversion" in active
        assert "liquidity_edge" in active

    def test_st06_get_state_returns_full_copy(self) -> None:
        """ST-06: get_state() returns a copy of the full state dict."""
        mgr = _make_manager()
        state = mgr.get_state()
        assert set(state.keys()) == set(KNOWN_STRATEGIES)
        # Mutating the returned dict must not affect the manager
        state["ev_momentum"] = False
        assert mgr.is_active("ev_momentum") is True

    def test_st07_is_active_known_strategy(self) -> None:
        """ST-07: is_active() returns correct bool for known strategies."""
        mgr = _make_manager(mean_reversion=False)
        assert mgr.is_active("mean_reversion") is False
        assert mgr.is_active("liquidity_edge") is True

    def test_st08_is_active_unknown_returns_false(self) -> None:
        """ST-08: is_active() returns False for unknown strategy names."""
        mgr = _make_manager()
        assert mgr.is_active("does_not_exist") is False

    def test_st09_last_strategy_disabled_auto_enables_all(self) -> None:
        """ST-09: Disabling the last active strategy triggers failsafe — all re-enabled."""
        mgr = _make_manager(ev_momentum=True, mean_reversion=False, liquidity_edge=False)
        result = mgr.toggle("ev_momentum")  # would disable the last active
        # Failsafe restores all strategies; result should be True (all enabled)
        assert result is True
        assert all(mgr.is_active(s) for s in KNOWN_STRATEGIES)


# ══════════════════════════════════════════════════════════════════════════════
# ST-10 — ST-17: StrategyStateManager persistence
# ══════════════════════════════════════════════════════════════════════════════


class TestSTManagerPersistence:
    """Persistence load/save tests using async mocks."""

    async def test_st10_load_uses_db_data(self) -> None:
        """ST-10: load() applies DB data when db is provided and non-empty."""
        mgr = _make_manager()
        db = MagicMock()
        db.load_strategy_state = AsyncMock(
            return_value={"ev_momentum": False, "mean_reversion": True, "liquidity_edge": True}
        )

        await mgr.load(db=db)

        assert mgr.is_active("ev_momentum") is False
        assert mgr.is_active("mean_reversion") is True
        db.load_strategy_state.assert_called_once()

    async def test_st11_load_falls_back_to_redis_when_db_empty(self) -> None:
        """ST-11: load() uses Redis when DB returns empty dict."""
        mgr = _make_manager()
        db = MagicMock()
        db.load_strategy_state = AsyncMock(return_value={})

        redis = MagicMock()
        redis._get_json = AsyncMock(
            return_value={"ev_momentum": False, "mean_reversion": True, "liquidity_edge": True}
        )

        await mgr.load(redis=redis, db=db)

        assert mgr.is_active("ev_momentum") is False
        redis._get_json.assert_called_once()

    async def test_st12_load_uses_defaults_when_no_backend(self) -> None:
        """ST-12: load() keeps in-memory defaults when neither backend is provided."""
        mgr = _make_manager()
        await mgr.load()
        assert all(mgr.is_active(s) for s in KNOWN_STRATEGIES)

    async def test_st13_load_falls_back_on_db_error(self) -> None:
        """ST-13: load() falls back to defaults when DB raises an exception."""
        mgr = _make_manager()
        db = MagicMock()
        db.load_strategy_state = AsyncMock(side_effect=RuntimeError("DB unavailable"))

        await mgr.load(db=db)
        # Should fall back to all-enabled defaults
        assert all(mgr.is_active(s) for s in KNOWN_STRATEGIES)

    async def test_st14_save_writes_to_db(self) -> None:
        """ST-14: save() calls db.save_strategy_state when db is provided."""
        mgr = _make_manager()
        db = MagicMock()
        db.save_strategy_state = AsyncMock(return_value=True)

        result = await mgr.save(db=db)

        assert result is True
        db.save_strategy_state.assert_called_once_with(mgr.get_state())

    async def test_st15_save_writes_to_redis(self) -> None:
        """ST-15: save() calls redis._set_json when redis is provided."""
        mgr = _make_manager()
        redis = MagicMock()
        redis._set_json = AsyncMock(return_value=True)

        result = await mgr.save(redis=redis)

        assert result is True
        redis._set_json.assert_called_once()

    async def test_st16_save_returns_false_no_backend(self) -> None:
        """ST-16: save() returns False when neither db nor redis is provided."""
        mgr = _make_manager()
        result = await mgr.save()
        assert result is False

    async def test_st17_save_returns_true_if_at_least_one_succeeds(self) -> None:
        """ST-17: save() returns True if DB fails but Redis succeeds."""
        mgr = _make_manager()
        db = MagicMock()
        db.save_strategy_state = AsyncMock(return_value=False)
        redis = MagicMock()
        redis._set_json = AsyncMock(return_value=True)

        result = await mgr.save(redis=redis, db=db)

        assert result is True


# ══════════════════════════════════════════════════════════════════════════════
# ST-18 — ST-19: DatabaseClient strategy_state helpers
# ══════════════════════════════════════════════════════════════════════════════


class TestDBClientStrategyState:
    """DatabaseClient.load_strategy_state / save_strategy_state behaviour."""

    async def test_st18_load_returns_empty_when_no_rows(self) -> None:
        """ST-18: load_strategy_state() returns {} when _fetch returns no rows."""
        from projects.polymarket.polyquantbot.infra.db import DatabaseClient

        client = DatabaseClient(dsn="postgresql://fake:5432/fake")
        # Patch _fetch to simulate DB unavailable (returns empty list)
        client._fetch = AsyncMock(return_value=[])

        result = await client.load_strategy_state()
        assert result == {}

    async def test_st19_save_returns_true_on_empty_state(self) -> None:
        """ST-19: save_strategy_state() returns True immediately for empty state."""
        from projects.polymarket.polyquantbot.infra.db import DatabaseClient

        client = DatabaseClient(dsn="postgresql://fake:5432/fake")

        result = await client.save_strategy_state({})
        assert result is True


# ══════════════════════════════════════════════════════════════════════════════
# ST-20 — ST-22: signal_engine strategy guard
# ══════════════════════════════════════════════════════════════════════════════


class TestSignalEngineStrategyGuard:
    """generate_signals() respects the active strategy guard."""

    async def test_st20_all_strategies_disabled_returns_empty(self) -> None:
        """ST-20: strategy_state with all False → returns [] immediately."""
        all_off = {s: False for s in KNOWN_STRATEGIES}
        signals = await generate_signals(
            [_market()],
            bankroll=1000.0,
            strategy_state=all_off,
        )
        assert signals == []

    async def test_st21_strategy_state_none_generates_signals(self) -> None:
        """ST-21: strategy_state=None bypasses guard and generates signals normally."""
        signals = await generate_signals(
            [_market()],
            bankroll=1000.0,
            strategy_state=None,
            edge_threshold=0.0,
            min_liquidity_usd=0.0,
            min_confidence=0.0,
        )
        assert len(signals) >= 1

    async def test_st22_at_least_one_active_strategy_generates_signals(self) -> None:
        """ST-22: strategy_state with at least one True → signals generated."""
        partial = {"ev_momentum": True, "mean_reversion": False, "liquidity_edge": False}
        signals = await generate_signals(
            [_market()],
            bankroll=1000.0,
            strategy_state=partial,
            edge_threshold=0.0,
            min_liquidity_usd=0.0,
            min_confidence=0.0,
        )
        assert len(signals) >= 1
