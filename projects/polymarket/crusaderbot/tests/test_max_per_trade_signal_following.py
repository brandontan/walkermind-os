"""Per-user "Max trade setting" now applies to signal_following too.

Bug: _resolve_size_usdc (the default-strategy sizer) capped only by
available_balance × capital_allocation_pct and ignored the user's explicit
per-trade ceiling (max_per_trade_mode/usdc/pct) — only late_entry_v3 honored it.
So a user's "max $X / Y% per trade" was silently ineffective on the default
strategy. Fix applies the EXPLICIT (fixed/pct) ceiling; 'auto' is unchanged
(we do NOT impose the candle-strategy $25 default on signal_following).
"""
from __future__ import annotations

from projects.polymarket.crusaderbot.services.signal_feed.signal_evaluator import (
    _resolve_size_usdc,
)
from projects.polymarket.crusaderbot.domain.strategy.types import UserContext


def _ctx(**kw) -> UserContext:
    base = dict(
        user_id="u", sub_account_id="s", risk_profile="balanced",
        capital_allocation_pct=0.6, available_balance_usdc=1000.0,
    )
    base.update(kw)
    return UserContext(**base)


def test_fixed_per_trade_cap_applies_to_signal_following():
    # capital cap = 1000*0.6 = 600; payload 500; explicit fixed $50 → 50
    ctx = _ctx(max_per_trade_mode="fixed", max_per_trade_usdc=50.0)
    assert _resolve_size_usdc({"size_usdc": 500}, ctx) == 50.0


def test_pct_per_trade_cap_applies_to_signal_following():
    # pct 2% of 1000 = 20 → min(500, 600, 20) = 20
    ctx = _ctx(max_per_trade_mode="pct", max_per_trade_pct=0.02)
    assert _resolve_size_usdc({"size_usdc": 500}, ctx) == 20.0


def test_auto_mode_not_capped_to_candle_default():
    # 'auto' must NOT impose the $25 candle default; only the capital cap applies
    ctx = _ctx(max_per_trade_mode="auto")
    assert _resolve_size_usdc({"size_usdc": 100}, ctx) == 100.0


def test_auto_mode_capital_allocation_cap_still_applies():
    ctx = _ctx(max_per_trade_mode="auto", capital_allocation_pct=0.6)
    # payload 5000, capital cap 600 → 600
    assert _resolve_size_usdc({"size_usdc": 5000}, ctx) == 600.0


def test_fixed_cap_overrides_larger_capital_cap():
    # capital cap 600 but explicit fixed $120 → 120 (the smaller wins)
    ctx = _ctx(max_per_trade_mode="fixed", max_per_trade_usdc=120.0)
    assert _resolve_size_usdc({"size_usdc": 500}, ctx) == 120.0
