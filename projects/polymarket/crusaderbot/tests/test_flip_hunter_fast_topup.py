"""Regression: flip-hunter fast top-up
(WARP/R00T/flip-hunter-fast-topup, ref Polybot directive 1.5 + 1.3.2).

After a successful safe_close / flip_hunter entry that leaves the user's
per-market exposure imbalanced (`|imbalance_usdc| >= FAST_TOPUP_MIN_USDC`),
the scanner fires an opposite-leg top-up via the standard TradeEngine
path. Cooldown per (user, market) prevents the same pair from spinning
top-ups within `FAST_TOPUP_COOLDOWN_SECONDS`.

Default OFF — dark launch like Lane B + D-2. Scope: only `safe_close` /
`flip_hunter` presets after a successful lead entry.

Guard lives in:
  ``services.signal_scan.signal_scan_job._maybe_fire_fast_topup`` +
  injection at the success branch of ``_process_candidate``.
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


_USER_UUID = UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
_MARKET_ID = "fast-topup-market"


@pytest.fixture(autouse=True)
def _isolated_state():
    StrategyRegistry._reset_for_tests()
    ssj._bankroll_reset_for_tests()
    ssj._fast_topup_reset_for_tests()
    crusaderbot_config.get_settings.cache_clear()
    yield
    StrategyRegistry._reset_for_tests()
    ssj._bankroll_reset_for_tests()
    ssj._fast_topup_reset_for_tests()
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


def test_fast_topup_helper_present():
    """`_maybe_fire_fast_topup` must exist as the canonical entry
    point; a regression that removed it would silently drop the lane.
    """
    assert hasattr(ssj, "_maybe_fire_fast_topup")


def test_fast_topup_wired_at_success_path():
    """The success branch of `_process_candidate` must invoke the
    top-up helper. Removal would silently disable post-fill chasing
    even with the config flag ON."""
    src = inspect.getsource(ssj._process_candidate)
    assert "_maybe_fire_fast_topup" in src
    assert "if inserted:" in src  # gated on a real fill, not duplicate


def test_fast_topup_reads_config_knobs():
    """The helper must read all three config knobs by name so the
    operator can disable/retune any one of them without redeploy."""
    src = inspect.getsource(ssj._maybe_fire_fast_topup)
    assert "FLIP_HUNTER_FAST_TOPUP_ENABLED" in src
    assert "FAST_TOPUP_MIN_USDC" in src
    assert "FAST_TOPUP_COOLDOWN_SECONDS" in src


def test_fast_topup_scoped_to_eligible_presets():
    """Scope must include `safe_close` AND `flip_hunter` only —
    `close_sweep` and other presets must NOT trigger top-ups."""
    src = inspect.getsource(ssj)
    assert '_FAST_TOPUP_ELIGIBLE_PRESETS' in src
    assert ssj._FAST_TOPUP_ELIGIBLE_PRESETS == frozenset(
        {"flip_hunter", "safe_close"},
    )


# ---------------------------------------------------------------------
# Config knob — defaults + validators.
# ---------------------------------------------------------------------


def test_fast_topup_default_is_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.delenv("FLIP_HUNTER_FAST_TOPUP_ENABLED", raising=False)
    s = crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert s.FLIP_HUNTER_FAST_TOPUP_ENABLED is False


def test_fast_topup_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.delenv("FAST_TOPUP_MIN_USDC", raising=False)
    monkeypatch.delenv("FAST_TOPUP_COOLDOWN_SECONDS", raising=False)
    s = crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert s.FAST_TOPUP_MIN_USDC == 5.0
    assert s.FAST_TOPUP_COOLDOWN_SECONDS == 15.0


@pytest.mark.parametrize("bad", ["0", "-1.0", "nan", "inf", "-inf"])
def test_fast_topup_min_usdc_rejects_invalid(
    monkeypatch: pytest.MonkeyPatch, bad: str,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("FAST_TOPUP_MIN_USDC", bad)
    with pytest.raises(Exception) as excinfo:
        crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert "FAST_TOPUP_MIN_USDC" in str(excinfo.value)


@pytest.mark.parametrize("bad", ["0", "-5", "nan", "inf"])
def test_fast_topup_cooldown_rejects_invalid(
    monkeypatch: pytest.MonkeyPatch, bad: str,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("FAST_TOPUP_COOLDOWN_SECONDS", bad)
    with pytest.raises(Exception) as excinfo:
        crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert "FAST_TOPUP_COOLDOWN_SECONDS" in str(excinfo.value)


# ---------------------------------------------------------------------
# Behavioural — drive the helper directly.
# ---------------------------------------------------------------------


def _row(*, active_preset: str = "safe_close") -> dict:
    return {
        "user_id": _USER_UUID,
        "telegram_user_id": 88,
        "role": "user",
        "auto_trade_on": True,
        "paused": False,
        "balance_usdc": 500.0,
        "tp_pct": 0.20,
        "sl_pct": 0.08,
        "daily_loss_override": None,
        "active_preset": active_preset,
        "resolved_profile": "balanced",
        "trading_mode": "paper",
        "live_capital_cap_usdc": 0.0,
    }


def _market() -> dict:
    return {
        "id": _MARKET_ID,
        "slug": "fast-topup-market",
        "question": "Will X happen?",
        "status": "active",
        "yes_price": 0.65,
        "no_price": 0.35,
        "yes_token_id": "tok_yes",
        "no_token_id": "tok_no",
        "liquidity_usdc": 20000.0,
    }


def _inv(yes_size: float, no_size: float) -> MarketInventory:
    return MarketInventory(
        user_id=str(_USER_UUID),
        market_id=_MARKET_ID,
        yes_size_usdc=Decimal(str(yes_size)),
        no_size_usdc=Decimal(str(no_size)),
        yes_count=1 if yes_size > 0 else 0,
        no_count=1 if no_size > 0 else 0,
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
        final_size_usdc=Decimal("5"),
    )


def _rejected_result() -> TradeResult:
    return TradeResult(
        approved=False,
        mode="paper",
        order_id=None,
        position_id=None,
        rejection_reason="risk_gate_rejected",
        failed_gate_step=7,
        chosen_mode="paper",
        final_size_usdc=None,
    )


def _drive(
    *,
    row: dict,
    inventory: MarketInventory | None,
    just_filled_side: str = "yes",
    just_filled_size: Decimal = Decimal("10"),
    engine_result: TradeResult | None = None,
    live_price: float | None = 0.34,
):
    """Run `_maybe_fire_fast_topup` against mocked dependencies and
    return the resolved engine call args (or None if engine wasn't
    invoked)."""
    captured: dict = {"signal": None}

    async def _fake_execute(signal):
        captured["signal"] = signal
        return engine_result if engine_result is not None else _approved_result()

    async def _fake_inv(uid, mid):
        return inventory

    class _Log:
        def info(self, *a, **kw): pass
        def warning(self, *a, **kw): pass

    with patch.object(
        ssj, "_fetch_market_inventory_for_override",
        new=AsyncMock(side_effect=_fake_inv),
    ), patch.object(
        ssj, "get_live_market_price",
        new=AsyncMock(return_value=live_price),
    ), patch.object(
        ssj._engine, "execute", side_effect=_fake_execute,
    ):
        asyncio.run(
            ssj._maybe_fire_fast_topup(
                row=row, market=_market(),
                just_filled_side=just_filled_side,
                just_filled_size_usdc=just_filled_size,
                log=_Log(),
            )
        )
    return captured["signal"]


def test_disabled_does_not_fire(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("FLIP_HUNTER_FAST_TOPUP_ENABLED", "false")
    bootstrap_default_strategies()

    sig = _drive(row=_row(), inventory=_inv(20.0, 5.0))
    assert sig is None


def test_enabled_fires_topup_to_lagging_side(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """User has $20 YES + $5 NO ($15 imbalance > $5 threshold). YES
    just filled. Top-up must fire for NO at the live price."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("FLIP_HUNTER_FAST_TOPUP_ENABLED", "true")
    monkeypatch.setenv("FAST_TOPUP_MIN_USDC", "5.0")
    bootstrap_default_strategies()

    sig = _drive(row=_row(), inventory=_inv(20.0, 5.0))
    assert sig is not None
    assert sig.side == "no"
    assert sig.strategy_type == "fast_topup"
    assert sig.price == 0.34


def test_enabled_no_fire_below_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """User has $10 YES + $7 NO ($3 imbalance < $5 threshold)."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("FLIP_HUNTER_FAST_TOPUP_ENABLED", "true")
    monkeypatch.setenv("FAST_TOPUP_MIN_USDC", "5.0")
    bootstrap_default_strategies()

    sig = _drive(row=_row(), inventory=_inv(10.0, 7.0))
    assert sig is None


def test_enabled_no_fire_for_close_sweep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`close_sweep` preset is OUT of eligible set — top-up must not
    fire even with strong imbalance."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("FLIP_HUNTER_FAST_TOPUP_ENABLED", "true")
    bootstrap_default_strategies()

    sig = _drive(
        row=_row(active_preset="close_sweep"),
        inventory=_inv(20.0, 5.0),
    )
    assert sig is None


def test_enabled_no_fire_when_just_filled_side_is_already_lagging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the lead entry already targeted the lagging leg the helper
    must NOT fire — there's nothing to top up."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("FLIP_HUNTER_FAST_TOPUP_ENABLED", "true")
    monkeypatch.setenv("FAST_TOPUP_MIN_USDC", "5.0")
    bootstrap_default_strategies()

    # YES is the lagging side ($5 < $20 NO). just_filled was YES.
    sig = _drive(
        row=_row(),
        inventory=_inv(5.0, 20.0),  # NO-heavy → lag is YES
        just_filled_side="yes",
    )
    assert sig is None


def test_enabled_no_fire_on_empty_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the inventory query returns empty (race with the lead
    position commit, or test inventory mocked empty), the top-up
    must not fire."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("FLIP_HUNTER_FAST_TOPUP_ENABLED", "true")
    bootstrap_default_strategies()

    sig = _drive(
        row=_row(),
        inventory=MarketInventory.empty(_USER_UUID, _MARKET_ID),
    )
    assert sig is None


def test_cooldown_blocks_second_topup(monkeypatch: pytest.MonkeyPatch) -> None:
    """After a top-up fires the per-(user, market) cooldown must
    block a second one within the configured window."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("FLIP_HUNTER_FAST_TOPUP_ENABLED", "true")
    monkeypatch.setenv("FAST_TOPUP_MIN_USDC", "5.0")
    monkeypatch.setenv("FAST_TOPUP_COOLDOWN_SECONDS", "15.0")
    bootstrap_default_strategies()

    inv = _inv(20.0, 5.0)
    # First call fires.
    sig1 = _drive(row=_row(), inventory=inv)
    assert sig1 is not None
    # Second call within the window must skip.
    sig2 = _drive(row=_row(), inventory=inv)
    assert sig2 is None


def test_cooldown_stamps_even_on_rejected_topup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rejected top-up must still stamp the cooldown so we don't
    immediately re-fire the same attempt on the next tick (would be a
    feedback loop)."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("FLIP_HUNTER_FAST_TOPUP_ENABLED", "true")
    monkeypatch.setenv("FAST_TOPUP_MIN_USDC", "5.0")
    bootstrap_default_strategies()

    inv = _inv(20.0, 5.0)
    sig = _drive(row=_row(), inventory=inv, engine_result=_rejected_result())
    assert sig is not None  # the engine WAS called
    key = ssj._fast_topup_key(_USER_UUID, _MARKET_ID)
    assert key in ssj._fast_topup_last_at


def test_topup_size_capped_at_lead_size(monkeypatch: pytest.MonkeyPatch) -> None:
    """Imbalance is $30 but lead entry was only $5 — top-up size must
    cap at the lead size so we never escalate exposure beyond the
    initial commitment."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("FLIP_HUNTER_FAST_TOPUP_ENABLED", "true")
    monkeypatch.setenv("FAST_TOPUP_MIN_USDC", "5.0")
    bootstrap_default_strategies()

    sig = _drive(
        row=_row(),
        inventory=_inv(35.0, 5.0),  # imbalance $30
        just_filled_size=Decimal("5"),
    )
    assert sig is not None
    assert sig.proposed_size_usdc == Decimal("5")


def test_topup_falls_back_to_market_price_on_live_fetch_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When live_market_price returns None (RPC stalled) the helper
    must fall back to the market row's stored price (binary
    invariant: NO price = 1 - YES price). Defensive — the lead entry
    succeeded so we still trust the row's snapshot."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("FLIP_HUNTER_FAST_TOPUP_ENABLED", "true")
    monkeypatch.setenv("FAST_TOPUP_MIN_USDC", "5.0")
    bootstrap_default_strategies()

    sig = _drive(
        row=_row(),
        inventory=_inv(20.0, 5.0),
        live_price=None,  # forces fallback
    )
    assert sig is not None
    # market.no_price = 0.35
    assert sig.price == 0.35
