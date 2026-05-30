"""Regression: close-sweep dual-leg execution
(WARP/R00T/close-sweep-dual-leg, ref Polybot directive 1.1.2.c).

Extends the Lane D-3 fast-topup mechanism to `close_sweep` candidates.
The directive specifies close_sweep should enter BOTH legs
simultaneously via TAKER orders (the final 35s entry window is too
tight for staged placement). Our paper engine fills instantly, so
"simultaneous" collapses to "lead entry succeeds → immediately fire
opposite-leg top-up" — the same mechanism D-3 ships for safe_close /
flip_hunter.

Independent enable knob (`CLOSE_SWEEP_DUAL_LEG_ENABLED`) so the
operator can flip D-3 and D-4 separately. Shares the
`FAST_TOPUP_MIN_USDC` + `FAST_TOPUP_COOLDOWN_SECONDS` knobs from D-3
so the dashboards reflect a single unified mechanism.

Module under test:
  ``services.signal_scan.signal_scan_job._resolve_eligible_topup_presets``
  + ``_maybe_fire_fast_topup`` (D-3 helper, scope extended).
"""
from __future__ import annotations

import asyncio
import inspect
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
from projects.polymarket.crusaderbot.services.signal_scan import (
    signal_scan_job as ssj,
)
from projects.polymarket.crusaderbot.services.trade_engine import TradeResult


_USER_UUID = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
_MARKET_ID = "close-sweep-dual-leg-market"


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


def test_resolver_helper_present():
    """Pin: the runtime preset resolver must exist as a named helper."""
    assert hasattr(ssj, "_resolve_eligible_topup_presets")


def test_helper_uses_resolver():
    """`_maybe_fire_fast_topup` must call the resolver — a regression
    that re-hardcoded `_FAST_TOPUP_ELIGIBLE_PRESETS` would silently
    drop D-4's close_sweep coverage."""
    src = inspect.getsource(ssj._maybe_fire_fast_topup)
    assert "_resolve_eligible_topup_presets" in src


def test_close_sweep_preset_constant_pinned():
    """The D-4-specific preset set must contain exactly close_sweep.
    Any drift (e.g. accidentally adding safe_close here) would
    duplicate D-3's coverage and confuse the resolver's union."""
    assert ssj._CLOSE_SWEEP_DUAL_LEG_PRESETS == frozenset({"close_sweep"})


# ---------------------------------------------------------------------
# Resolver behaviour — flag-combination matrix.
# ---------------------------------------------------------------------


class _Cfg:
    """Minimal config object with the two boolean flags. `getattr`
    fallback in the resolver makes additional fields irrelevant."""
    def __init__(self, *, flip_hunter: bool, close_sweep: bool):
        self.FLIP_HUNTER_FAST_TOPUP_ENABLED = flip_hunter
        self.CLOSE_SWEEP_DUAL_LEG_ENABLED = close_sweep


def test_resolver_both_disabled_returns_empty():
    presets = ssj._resolve_eligible_topup_presets(
        _Cfg(flip_hunter=False, close_sweep=False),
    )
    assert presets == frozenset()


def test_resolver_only_flip_hunter_enabled():
    """D-3 ON, D-4 OFF: safe_close + flip_hunter eligible; close_sweep NOT."""
    presets = ssj._resolve_eligible_topup_presets(
        _Cfg(flip_hunter=True, close_sweep=False),
    )
    assert presets == frozenset({"safe_close", "flip_hunter"})


def test_resolver_only_close_sweep_enabled():
    """D-3 OFF, D-4 ON: close_sweep eligible; safe_close + flip_hunter NOT.

    This is the key independence guarantee: the operator can enable
    close_sweep dual-leg without also opting into the safe_close /
    flip_hunter post-fill chase.
    """
    presets = ssj._resolve_eligible_topup_presets(
        _Cfg(flip_hunter=False, close_sweep=True),
    )
    assert presets == frozenset({"close_sweep"})


def test_resolver_both_enabled_returns_union():
    presets = ssj._resolve_eligible_topup_presets(
        _Cfg(flip_hunter=True, close_sweep=True),
    )
    assert presets == frozenset({"safe_close", "flip_hunter", "close_sweep"})


def test_resolver_missing_attrs_defaults_to_disabled():
    """`getattr(..., False)` fallback: a config object that's missing
    one or both attributes is treated as disabled, not crashed. Guards
    against partial config-class drift between deploys."""
    class _Partial:
        pass
    presets = ssj._resolve_eligible_topup_presets(_Partial())
    assert presets == frozenset()


def test_resolver_none_input_returns_empty():
    """Defensive: a None config (config-init failure upstream) must
    NOT raise AttributeError. Returns an empty frozenset so the
    caller's "neither flag is on" short-circuit kicks in."""
    assert ssj._resolve_eligible_topup_presets(None) == frozenset()


# ---------------------------------------------------------------------
# Config knob.
# ---------------------------------------------------------------------


def test_close_sweep_dual_leg_default_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.delenv("CLOSE_SWEEP_DUAL_LEG_ENABLED", raising=False)
    s = crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert s.CLOSE_SWEEP_DUAL_LEG_ENABLED is False


# ---------------------------------------------------------------------
# Behavioural — drive the helper directly (mirrors D-3 test surface).
# ---------------------------------------------------------------------


def _row(*, active_preset: str = "close_sweep") -> dict:
    return {
        "user_id": _USER_UUID,
        "telegram_user_id": 99,
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
        "slug": "close-sweep-dual-leg-market",
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


def _tight_book() -> dict:
    """Default book for the lagging leg: spread = 0.01, well under the
    0.02 CLOSE_SWEEP_MAX_LEG_SPREAD default — spread guard passes."""
    return {
        "asks": [{"price": "0.35", "size": "100"}],
        "bids": [{"price": "0.34", "size": "100"}],
    }


def _drive(
    *,
    row: dict,
    inventory: MarketInventory | None,
    just_filled_side: str = "yes",
    just_filled_size: Decimal = Decimal("10"),
    engine_result: TradeResult | None = None,
    book: dict | None = None,
):
    captured: dict = {"signal": None}

    async def _fake_execute(signal):
        captured["signal"] = signal
        return engine_result if engine_result is not None else _approved_result()

    async def _fake_inv(uid, mid):
        return inventory

    _book = book if book is not None else _tight_book()

    class _Log:
        def info(self, *a, **kw): pass
        def warning(self, *a, **kw): pass

    with patch.object(
        ssj, "_fetch_market_inventory_for_override",
        new=AsyncMock(side_effect=_fake_inv),
    ), patch.object(
        ssj, "get_live_market_price",
        new=AsyncMock(return_value=0.34),
    ), patch.object(
        ssj._polymarket, "get_book",
        new=AsyncMock(return_value=_book),
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


def test_close_sweep_does_not_fire_with_neither_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default OFF state: close_sweep entry is unchanged from pre-lane."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("FLIP_HUNTER_FAST_TOPUP_ENABLED", "false")
    monkeypatch.setenv("CLOSE_SWEEP_DUAL_LEG_ENABLED", "false")
    bootstrap_default_strategies()

    sig = _drive(row=_row(), inventory=_inv(20.0, 0.0))
    assert sig is None


def test_close_sweep_fires_when_dual_leg_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-4 enabled. close_sweep candidate just filled YES → top-up
    fires for NO."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("FLIP_HUNTER_FAST_TOPUP_ENABLED", "false")
    monkeypatch.setenv("CLOSE_SWEEP_DUAL_LEG_ENABLED", "true")
    monkeypatch.setenv("FAST_TOPUP_MIN_USDC", "5.0")
    bootstrap_default_strategies()

    sig = _drive(row=_row(), inventory=_inv(20.0, 0.0))
    assert sig is not None
    assert sig.side == "no"
    assert sig.strategy_type == "fast_topup"


def test_close_sweep_does_not_fire_when_only_flip_hunter_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-3 ON, D-4 OFF: a close_sweep entry must NOT trigger top-up
    even though the imbalance is significant. Independence guarantee.
    """
    _set_required_env(monkeypatch)
    monkeypatch.setenv("FLIP_HUNTER_FAST_TOPUP_ENABLED", "true")
    monkeypatch.setenv("CLOSE_SWEEP_DUAL_LEG_ENABLED", "false")
    bootstrap_default_strategies()

    sig = _drive(row=_row(active_preset="close_sweep"), inventory=_inv(20.0, 0.0))
    assert sig is None


def test_safe_close_still_fires_when_only_dual_leg_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-3 OFF, D-4 ON: safe_close entry must NOT trigger top-up.
    Symmetric to the previous test — confirms the two flags scope
    cleanly to their respective preset sets."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("FLIP_HUNTER_FAST_TOPUP_ENABLED", "false")
    monkeypatch.setenv("CLOSE_SWEEP_DUAL_LEG_ENABLED", "true")
    bootstrap_default_strategies()

    sig = _drive(row=_row(active_preset="safe_close"), inventory=_inv(20.0, 0.0))
    assert sig is None


def test_close_sweep_dual_leg_respects_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shared FAST_TOPUP_MIN_USDC threshold still applies to D-4
    even when D-3 is off — no separate close_sweep-specific bypass."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("FLIP_HUNTER_FAST_TOPUP_ENABLED", "false")
    monkeypatch.setenv("CLOSE_SWEEP_DUAL_LEG_ENABLED", "true")
    monkeypatch.setenv("FAST_TOPUP_MIN_USDC", "10.0")
    bootstrap_default_strategies()

    # Imbalance = $5 < $10 threshold → no top-up.
    sig = _drive(row=_row(), inventory=_inv(5.0, 0.0))
    assert sig is None


def test_close_sweep_dual_leg_respects_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shared FAST_TOPUP_COOLDOWN_SECONDS still applies — a second
    close_sweep top-up within the window must be blocked."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("FLIP_HUNTER_FAST_TOPUP_ENABLED", "false")
    monkeypatch.setenv("CLOSE_SWEEP_DUAL_LEG_ENABLED", "true")
    monkeypatch.setenv("FAST_TOPUP_MIN_USDC", "5.0")
    monkeypatch.setenv("FAST_TOPUP_COOLDOWN_SECONDS", "15.0")
    bootstrap_default_strategies()

    inv = _inv(20.0, 0.0)
    sig1 = _drive(row=_row(), inventory=inv)
    assert sig1 is not None
    sig2 = _drive(row=_row(), inventory=inv)
    assert sig2 is None


# ---------------------------------------------------------------------------
# M-2 hardening: close_sweep spread guard
# (WARP/R00T/close-sweep-dual-leg-spread-guard)
# ---------------------------------------------------------------------------


def test_close_sweep_topup_wide_spread_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """close_sweep top-up must be skipped when the lagging leg's spread
    exceeds CLOSE_SWEEP_MAX_LEG_SPREAD (mirrors the lead scan-path gate)."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("CLOSE_SWEEP_DUAL_LEG_ENABLED", "true")
    monkeypatch.setenv("FAST_TOPUP_MIN_USDC", "5.0")
    monkeypatch.setenv("CLOSE_SWEEP_MAX_LEG_SPREAD", "0.02")
    bootstrap_default_strategies()

    wide_book = {
        "asks": [{"price": "0.40", "size": "10"}],
        "bids": [{"price": "0.34", "size": "10"}],  # spread = 0.06 > 0.02
    }
    sig = _drive(row=_row(), inventory=_inv(20.0, 0.0), book=wide_book)
    assert sig is None


def test_close_sweep_topup_tight_spread_fires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """close_sweep top-up fires when the lagging leg spread is within limit."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("CLOSE_SWEEP_DUAL_LEG_ENABLED", "true")
    monkeypatch.setenv("FAST_TOPUP_MIN_USDC", "5.0")
    monkeypatch.setenv("CLOSE_SWEEP_MAX_LEG_SPREAD", "0.02")
    bootstrap_default_strategies()

    sig = _drive(row=_row(), inventory=_inv(20.0, 0.0))  # default _tight_book (0.01)
    assert sig is not None
    assert sig.side == "no"


def test_close_sweep_topup_missing_bid_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """close_sweep top-up must be skipped when the lagging leg book has no
    bids (thin-book / no-buyer scenario in the final 35s window)."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("CLOSE_SWEEP_DUAL_LEG_ENABLED", "true")
    monkeypatch.setenv("FAST_TOPUP_MIN_USDC", "5.0")
    bootstrap_default_strategies()

    no_bid_book = {
        "asks": [{"price": "0.40", "size": "10"}],
        "bids": [],
    }
    sig = _drive(row=_row(), inventory=_inv(20.0, 0.0), book=no_bid_book)
    assert sig is None
