"""Regression: safe-close inventory imbalance override
(WARP/R00T/safe-close-imbalance-override, ref Polybot directive 1.2.1.c).

When a safe_close late_entry_v3 candidate fires on a market where the
user already holds imbalanced exposure
(|imbalance_usdc| > config.SAFE_CLOSE_IMBALANCE_THRESHOLD_USDC), the
scanner:

  1. Computes inventory via
     ``domain.strategy.inventory.compute_market_inventory``.
  2. Identifies the lagging leg (less exposure side).
  3. If the candidate's intended side differs from the lagging leg,
     mutates the candidate side via ``dataclasses.replace`` (the
     SignalCandidate dataclass is frozen) and stamps
     ``metadata["imbalance_override"]`` for audit.
  4. Replaces the broad open-position dedup with the side-aware
     variant ``_has_open_position_for_side`` so the override can
     actually fire — the standard dedup would block any second
     market-level entry.

Default OFF (``SAFE_CLOSE_IMBALANCE_OVERRIDE_ENABLED=false``) — dark
launch like the bankroll circuit breaker. Other strategies / presets
keep the broad open-position dedup unchanged.

Guard lives in:
  ``services.signal_scan.signal_scan_job._process_candidate`` step 1a-2
Helper:
  ``services.signal_scan.signal_scan_job._has_open_position_for_side``
"""
from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest

from projects.polymarket.crusaderbot import config as crusaderbot_config
from projects.polymarket.crusaderbot.domain.strategy import (
    StrategyRegistry,
    bootstrap_default_strategies,
)
from projects.polymarket.crusaderbot.domain.strategy.inventory import MarketInventory
from projects.polymarket.crusaderbot.domain.strategy.types import SignalCandidate
from projects.polymarket.crusaderbot.services.signal_scan import (
    signal_scan_job as ssj,
)
from projects.polymarket.crusaderbot.services.trade_engine import TradeResult


_USER_UUID = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
_MARKET_ID = "imbalance-override-market"


@pytest.fixture(autouse=True)
def _isolated_state():
    StrategyRegistry._reset_for_tests()
    ssj._bankroll_reset_for_tests()
    crusaderbot_config.get_settings.cache_clear()
    yield
    StrategyRegistry._reset_for_tests()
    ssj._bankroll_reset_for_tests()
    crusaderbot_config.get_settings.cache_clear()


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("OPERATOR_CHAT_ID", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("WALLET_HD_SEED", "seed")
    monkeypatch.setenv("WALLET_ENCRYPTION_KEY", "k")
    monkeypatch.setenv("POLYGON_RPC_URL", "https://rpc")
    monkeypatch.setenv("ALCHEMY_POLYGON_WS_URL", "wss://ws")


# ---------------------------------------------------------------------
# Source-level pins.
# ---------------------------------------------------------------------


def test_process_candidate_has_imbalance_override_path():
    """Override path must be present in _process_candidate. Removing
    it would silently revert the lane."""
    src = inspect.getsource(ssj._process_candidate)
    assert "imbalance_override_applied" in src
    assert "SAFE_CLOSE_IMBALANCE_OVERRIDE_ENABLED" in src


def test_process_candidate_scoped_to_safe_close():
    """The override gate must check both `strategy_name == late_entry_v3`
    AND `active_preset == safe_close`. A regression that dropped either
    check would over-fire on close_sweep / flip_hunter."""
    src = inspect.getsource(ssj._process_candidate)
    assert 'cand.strategy_name == "late_entry_v3"' in src
    assert '"safe_close"' in src


def test_process_candidate_uses_side_aware_dedup():
    """When override is active the dedup must switch to the side-aware
    variant. A regression that always used `_has_open_position_for_market`
    would block every rebalance even when the lagging-leg side is empty."""
    src = inspect.getsource(ssj._process_candidate)
    assert "_has_open_position_for_side" in src
    assert "_imbalance_override_active" in src


def test_dataclass_replace_used_not_attribute_assignment():
    """`SignalCandidate` is `frozen=True` so direct attribute assignment
    raises `FrozenInstanceError`. Pin that the override uses
    `dataclasses.replace` (imported as `_dc_replace`) so a regression
    that flips back to mutation surfaces immediately."""
    src = inspect.getsource(ssj._process_candidate)
    assert "_dc_replace(" in src and "metadata=_new_md" in src


# ---------------------------------------------------------------------
# Config knob — defaults + validators.
# ---------------------------------------------------------------------


def test_override_default_is_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default OFF so the lane ships dark-launched."""
    _set_required_env(monkeypatch)
    monkeypatch.delenv("SAFE_CLOSE_IMBALANCE_OVERRIDE_ENABLED", raising=False)
    s = crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert s.SAFE_CLOSE_IMBALANCE_OVERRIDE_ENABLED is False


def test_threshold_default_is_5_usdc(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.delenv("SAFE_CLOSE_IMBALANCE_THRESHOLD_USDC", raising=False)
    s = crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert s.SAFE_CLOSE_IMBALANCE_THRESHOLD_USDC == 5.0


@pytest.mark.parametrize("bad", ["0", "-1.0", "nan", "inf", "-inf"])
def test_threshold_rejects_invalid(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    """Threshold <= 0 or non-finite must fail at config load (gate
    branches on `> threshold`; 0 would over-fire on any imbalance,
    NaN comparisons are always False so NaN would silently disable)."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("SAFE_CLOSE_IMBALANCE_THRESHOLD_USDC", bad)
    with pytest.raises(Exception) as excinfo:
        crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert "SAFE_CLOSE_IMBALANCE_THRESHOLD_USDC" in str(excinfo.value)


# ---------------------------------------------------------------------
# Behavioural integration.
# ---------------------------------------------------------------------


def _user_row(*, balance: float = 500.0, active_preset: str | None = "safe_close") -> dict:
    return {
        "user_id": _USER_UUID,
        "telegram_user_id": 88,
        "auto_trade_on": True,
        "paused": False,
        "balance_usdc": balance,
        "risk_profile": "balanced",
        "trading_mode": "paper",
        "tp_pct": 0.20,
        "sl_pct": 0.08,
        "daily_loss_override": None,
        "capital_allocation_pct": 0.10,
        "sub_account_id": uuid4(),
        "resolved_profile": "balanced",
        "active_preset": active_preset,
    }


def _market_row() -> dict:
    return {
        "id": _MARKET_ID,
        "slug": "imbalance-override-market",
        "question": "Will X happen?",
        "status": "active",
        "yes_price": 0.65,
        "no_price": 0.35,
        "yes_token_id": "tok_yes",
        "no_token_id": "tok_no",
        "liquidity_usdc": 20000.0,
    }


def _safe_close_candidate(side: str = "YES") -> SignalCandidate:
    return SignalCandidate(
        market_id=_MARKET_ID,
        condition_id=_MARKET_ID,
        side=side,
        confidence=0.7,
        suggested_size_usdc=10.0,
        strategy_name="late_entry_v3",
        signal_ts=datetime.now(timezone.utc),
        metadata={
            "market_id": _MARKET_ID,
            "entry_price": 0.65,
            "fav_price_min": 0.60,
            "fav_price_max": 0.70,
            "underdog_mode": False,
            "entry_price_ts": datetime.now(timezone.utc).timestamp(),
            "complete_set_edge": 0.05,
        },
    )


def _approved_trade_result() -> TradeResult:
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


def _imbalanced_inventory(yes_size: float, no_size: float) -> MarketInventory:
    return MarketInventory(
        user_id=str(_USER_UUID),
        market_id=_MARKET_ID,
        yes_size_usdc=Decimal(str(yes_size)),
        no_size_usdc=Decimal(str(no_size)),
        yes_count=1 if yes_size > 0 else 0,
        no_count=1 if no_size > 0 else 0,
    )


def _run(*, row: dict, cand: SignalCandidate, inventory: MarketInventory | None = None,
         dup_market: bool = False, dup_side: bool = False) -> dict:
    """Drive _process_candidate. Returns a dict capturing the final
    engine signal (or None if engine was never called) + the candidate
    that reached the engine."""
    seen: dict = {"engine_called": False, "signal": None, "final_side": None}

    async def _track_execute(signal):
        seen["engine_called"] = True
        seen["signal"] = signal
        seen["final_side"] = signal.side
        return _approved_trade_result()

    async def _fake_fetch_inventory(user_id, market_id):
        return inventory if inventory is not None else MarketInventory.empty(
            str(user_id), market_id,
        )

    with patch.object(ssj, "_load_stale_queued_row", return_value=None), \
            patch.object(ssj, "_publication_already_queued", return_value=False), \
            patch.object(ssj, "_has_open_position_for_market", return_value=dup_market), \
            patch.object(ssj, "_has_open_position_for_side", return_value=dup_side), \
            patch.object(ssj, "_load_market", return_value=_market_row()), \
            patch.object(ssj, "get_live_market_price",
                         new=AsyncMock(return_value=0.66)), \
            patch.object(ssj._engine, "execute", side_effect=_track_execute), \
            patch.object(ssj, "_insert_execution_queue", return_value=True), \
            patch.object(ssj, "_mark_executed", new=AsyncMock()), \
            patch.object(
                ssj, "_fetch_market_inventory_for_override",
                new=AsyncMock(side_effect=_fake_fetch_inventory),
            ):
        asyncio.run(ssj._process_candidate(row, cand))
    return seen


def test_disabled_override_passes_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """With override OFF (default) the candidate side is NOT mutated
    and the broad open-position dedup is used."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("SAFE_CLOSE_IMBALANCE_OVERRIDE_ENABLED", "false")
    bootstrap_default_strategies()

    result = _run(
        row=_user_row(),
        cand=_safe_close_candidate(side="YES"),
        inventory=_imbalanced_inventory(yes_size=30.0, no_size=5.0),
    )
    assert result["engine_called"] is True
    assert result["final_side"] == "yes"


def test_enabled_override_flips_side_when_imbalanced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """User has $30 YES + $5 NO ($25 imbalance > $5 threshold). Safe
    Close fires a YES candidate. Override must flip side to NO."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("SAFE_CLOSE_IMBALANCE_OVERRIDE_ENABLED", "true")
    monkeypatch.setenv("SAFE_CLOSE_IMBALANCE_THRESHOLD_USDC", "5.0")
    bootstrap_default_strategies()

    result = _run(
        row=_user_row(),
        cand=_safe_close_candidate(side="YES"),
        inventory=_imbalanced_inventory(yes_size=30.0, no_size=5.0),
        dup_market=True,   # broad dedup would block
        dup_side=False,    # but no NO position exists
    )
    assert result["engine_called"] is True
    assert result["final_side"] == "no"


def test_enabled_override_no_flip_when_below_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """User has $30 YES + $27 NO ($3 imbalance < $5 threshold). Override
    must NOT fire; standard broad dedup blocks the second entry."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("SAFE_CLOSE_IMBALANCE_OVERRIDE_ENABLED", "true")
    monkeypatch.setenv("SAFE_CLOSE_IMBALANCE_THRESHOLD_USDC", "5.0")
    bootstrap_default_strategies()

    result = _run(
        row=_user_row(),
        cand=_safe_close_candidate(side="YES"),
        inventory=_imbalanced_inventory(yes_size=30.0, no_size=27.0),
        dup_market=True,   # broad dedup blocks
    )
    assert result["engine_called"] is False


def test_enabled_override_no_flip_when_already_on_lagging_side(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """User has $30 YES + $5 NO. Safe Close fires a NO candidate
    (already targets the lagging side). No side mutation needed —
    but `_imbalance_override_active` is still set so the side-aware
    dedup applies. With `dup_side=False` (no existing NO position)
    the rebalance entry passes.

    This pins the Gemini-flagged correction: side-aware dedup must
    activate whenever |imbalance| > threshold, not only on a side
    flip — otherwise a correctly-directed rebalance is blocked by
    the broad market-wide dedup."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("SAFE_CLOSE_IMBALANCE_OVERRIDE_ENABLED", "true")
    monkeypatch.setenv("SAFE_CLOSE_IMBALANCE_THRESHOLD_USDC", "5.0")
    bootstrap_default_strategies()

    result = _run(
        row=_user_row(),
        cand=_safe_close_candidate(side="NO"),
        inventory=_imbalanced_inventory(yes_size=30.0, no_size=5.0),
        dup_market=True,   # broad dedup would block — but side-aware kicks in
        dup_side=False,    # no NO position yet → passes
    )
    assert result["engine_called"] is True
    assert result["final_side"] == "no"


def test_enabled_override_no_flip_for_close_sweep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """User has active_preset='close_sweep' (not safe_close). Override
    must NOT fire even with imbalanced inventory — the gate is scoped."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("SAFE_CLOSE_IMBALANCE_OVERRIDE_ENABLED", "true")
    monkeypatch.setenv("SAFE_CLOSE_IMBALANCE_THRESHOLD_USDC", "5.0")
    bootstrap_default_strategies()

    result = _run(
        row=_user_row(active_preset="close_sweep"),
        cand=_safe_close_candidate(side="YES"),
        inventory=_imbalanced_inventory(yes_size=30.0, no_size=5.0),
        dup_market=True,   # broad dedup blocks
    )
    assert result["engine_called"] is False


def test_enabled_override_no_flip_when_empty_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First entry on the market — no inventory. Override is a no-op;
    broad dedup also passes (no prior positions). Engine sees the
    original side."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("SAFE_CLOSE_IMBALANCE_OVERRIDE_ENABLED", "true")
    monkeypatch.setenv("SAFE_CLOSE_IMBALANCE_THRESHOLD_USDC", "5.0")
    bootstrap_default_strategies()

    result = _run(
        row=_user_row(),
        cand=_safe_close_candidate(side="YES"),
        inventory=MarketInventory.empty(_USER_UUID, _MARKET_ID),
        dup_market=False,
    )
    assert result["engine_called"] is True
    assert result["final_side"] == "yes"


def test_enabled_override_side_aware_dedup_blocks_same_lagging_side(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """User has $30 YES + $5 NO. Safe Close fires YES → override
    flips to NO. But user ALSO already has an open NO position (rare;
    happens when a prior rebalance landed but inventory still shows
    YES-heavy because the YES position is much larger). Side-aware
    dedup must block."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("SAFE_CLOSE_IMBALANCE_OVERRIDE_ENABLED", "true")
    monkeypatch.setenv("SAFE_CLOSE_IMBALANCE_THRESHOLD_USDC", "5.0")
    bootstrap_default_strategies()

    result = _run(
        row=_user_row(),
        cand=_safe_close_candidate(side="YES"),
        inventory=_imbalanced_inventory(yes_size=30.0, no_size=5.0),
        dup_side=True,   # NO position already open
    )
    assert result["engine_called"] is False
