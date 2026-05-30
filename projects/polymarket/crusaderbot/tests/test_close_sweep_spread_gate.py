"""Regression: close_sweep per-leg bid-ask spread gate
(WARP/R00T/close-sweep-spread-gate, Lane 2/5 Polybot directive).

Scoped to close_sweep — the preset that fires in the final ~35s before
candle close where book depth thins out and a wide per-leg spread (=
high slippage on a taker fill) is the dominant execution risk.
safe_close + flip_hunter enter earlier in the candle where the existing
complete-set `spread = yes_ask + no_ask` check is sufficient.

Mechanism:
  - `late_entry_v3._best_bid` mirrors `_best_ask` (scan, take highest bid).
  - `_evaluate_market(max_leg_spread=...)` rejects with reason
    `leg_spread_too_wide` when either side's (ask - bid) exceeds threshold.
  - `_resolve_preset_params("close_sweep")` injects
    `max_leg_spread=cfg.CLOSE_SWEEP_MAX_LEG_SPREAD` (default 0.02).
  - safe_close + flip_hunter dicts OMIT the key → call site passes None
    → gate no-ops for those presets.
  - Set `CLOSE_SWEEP_MAX_LEG_SPREAD=0` to disable (escape hatch).
"""
from __future__ import annotations

import inspect

import pytest

from projects.polymarket.crusaderbot import config as crusaderbot_config
from projects.polymarket.crusaderbot.domain.strategy.strategies import (
    late_entry_v3 as lev3,
)
from projects.polymarket.crusaderbot.services.signal_scan import (
    signal_scan_job as ssj,
)


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("OPERATOR_CHAT_ID", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("WALLET_HD_SEED", "seed")
    monkeypatch.setenv("WALLET_ENCRYPTION_KEY", "k")
    monkeypatch.setenv("POLYGON_RPC_URL", "https://rpc")
    monkeypatch.setenv("ALCHEMY_POLYGON_WS_URL", "wss://ws")


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    crusaderbot_config.get_settings.cache_clear()
    yield
    crusaderbot_config.get_settings.cache_clear()


# ---------------------------------------------------------------------
# _best_bid helper — mirror of _best_ask, takes highest positive price.
# ---------------------------------------------------------------------


def test_best_bid_picks_highest_positive_price():
    """Polymarket /book bid ordering is not guaranteed — scan + take max,
    mirroring the _best_ask invariant (which scans + takes min)."""
    book = {"bids": [
        {"price": "0.40", "size": "100"},
        {"price": "0.42", "size": "50"},
        {"price": "0.38", "size": "200"},
    ]}
    assert lev3._best_bid(book) == pytest.approx(0.42)


def test_best_bid_returns_none_on_empty():
    assert lev3._best_bid({"bids": []}) is None
    assert lev3._best_bid({}) is None
    assert lev3._best_bid(None) is None


def test_best_bid_skips_malformed_entries():
    book = {"bids": [
        {"price": "bad"},
        {"size": "10"},  # missing price
        {"price": "0.45", "size": "10"},
        {"price": "0", "size": "10"},  # 0 is invalid (must be > 0)
    ]}
    assert lev3._best_bid(book) == pytest.approx(0.45)


# ---------------------------------------------------------------------
# Source-level pins — gate code path + scope + config knob.
# ---------------------------------------------------------------------


def test_evaluate_market_signature_has_max_leg_spread():
    """`_evaluate_market` must accept `max_leg_spread` so the close_sweep
    branch in `_resolve_preset_params` can forward the threshold."""
    sig = inspect.signature(lev3._evaluate_market)
    assert "max_leg_spread" in sig.parameters, (
        "Regression: _evaluate_market signature lost the max_leg_spread "
        "parameter — close_sweep per-leg spread gate is now a no-op."
    )


def test_evaluate_market_has_leg_spread_gate():
    """Source pin: the gate body must contain the `leg_spread_too_wide`
    reject reason. A future edit that removes the gate but keeps the
    parameter would silently bypass the spread check."""
    src = inspect.getsource(lev3._evaluate_market)
    assert "leg_spread_too_wide" in src, (
        "Regression: _evaluate_market lost the per-leg spread gate."
    )
    # The gate must short-circuit on disable (`> 0` branch) so
    # CLOSE_SWEEP_MAX_LEG_SPREAD=0 escape hatch works.
    assert "max_leg_spread > 0" in src, (
        "Regression: per-leg spread gate must short-circuit when "
        "max_leg_spread is 0 (operator escape hatch)."
    )


def test_close_sweep_preset_injects_max_leg_spread():
    """`_resolve_preset_params("close_sweep")` must include the
    `max_leg_spread` key wired to config; safe_close + flip_hunter must
    NOT include it (no-op for them)."""
    src = inspect.getsource(ssj._resolve_preset_params)
    assert "CLOSE_SWEEP_MAX_LEG_SPREAD" in src, (
        "Regression: _resolve_preset_params must wire the close_sweep "
        "max_leg_spread to config.CLOSE_SWEEP_MAX_LEG_SPREAD."
    )


def test_scan_call_sites_forward_max_leg_spread():
    """Both scan call sites (run_close_sweep_fast + run_once Phase B2)
    must forward `max_leg_spread` from preset params to scan(), otherwise
    the gate is invisible to actual production traffic."""
    src_fast = inspect.getsource(ssj.run_close_sweep_fast)
    assert "max_leg_spread" in src_fast, (
        "Regression: run_close_sweep_fast lost the max_leg_spread "
        "forward — close_sweep candle trades bypass the gate."
    )
    src_run = inspect.getsource(ssj.run_once)
    assert "max_leg_spread" in src_run, (
        "Regression: run_once (Phase B2 late_entry_v3 scan) lost the "
        "max_leg_spread forward — main-loop close_sweep bypasses the gate."
    )


# ---------------------------------------------------------------------
# Config knob — default, env override, negative rejection.
# ---------------------------------------------------------------------


def test_close_sweep_max_leg_spread_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.delenv("CLOSE_SWEEP_MAX_LEG_SPREAD", raising=False)
    s = crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert s.CLOSE_SWEEP_MAX_LEG_SPREAD == pytest.approx(0.02)


def test_close_sweep_max_leg_spread_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("CLOSE_SWEEP_MAX_LEG_SPREAD", "0")
    s = crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert s.CLOSE_SWEEP_MAX_LEG_SPREAD == pytest.approx(0)


def test_close_sweep_max_leg_spread_rejects_negative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same trap as TOB_STALE_MS: the runtime branch is `> 0`, so -0.01
    would silently disable the gate the same as 0. Reject at load."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("CLOSE_SWEEP_MAX_LEG_SPREAD", "-0.01")
    with pytest.raises(Exception) as excinfo:
        crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert "CLOSE_SWEEP_MAX_LEG_SPREAD" in str(excinfo.value)


# ---------------------------------------------------------------------
# Behavioural — _evaluate_market accepts / rejects on per-leg spread.
# ---------------------------------------------------------------------


def _book(ask: float, bid: float) -> dict:
    """Minimal /book payload with one ask and one bid level."""
    return {
        "asks": [{"price": str(ask), "size": "100"}],
        "bids": [{"price": str(bid), "size": "100"}],
    }


def _market_dict(yes_book: dict, no_book: dict) -> dict:
    return {
        "conditionId": "cond-1",
        "slug": "btc-updown-5m-test",
        "closed": False,
        "active": True,
        "acceptingOrders": True,
        "clobTokenIds": ["yes_tok", "no_tok"],
        # Resolution 30s in the future so the close_sweep timing gate
        # (entry_window_sec=35, no min_entry_sec) admits the candidate.
        "endDate": None,
    }


def _evaluate_args(*, max_leg_spread: float | None) -> dict:
    from datetime import datetime, timezone
    from projects.polymarket.crusaderbot.domain.strategy.types import UserContext
    now = datetime(2026, 5, 30, 14, 0, 0, tzinfo=timezone.utc)
    return dict(
        blacklist=set(),
        user_context=UserContext(
            user_id="u",
            sub_account_id="u",
            risk_profile="balanced",
            capital_allocation_pct=0.10,
            available_balance_usdc=500.0,
        ),
        strategy_name="late_entry_v3",
        signal_ts=now,
        now_ts=now.timestamp(),
        min_ask_diff=0.02,
        entry_window_sec=35.0,
        fav_price_min=0.55,
        fav_price_max=0.70,
        min_entry_sec=None,
        underdog_mode=False,
        force_exit_at_rem_sec=None,
        max_leg_spread=max_leg_spread,
    )


def _market_with_seconds_left(yes_book: dict, no_book: dict, *, secs: float = 20.0) -> dict:
    from datetime import datetime, timedelta, timezone
    m = _market_dict(yes_book, no_book)
    end = datetime(2026, 5, 30, 14, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=secs)
    m["endDate"] = end.isoformat().replace("+00:00", "Z")
    return m


@pytest.mark.asyncio
async def test_evaluate_market_rejects_when_yes_leg_spread_too_wide(monkeypatch):
    """YES leg ask-bid = 0.04 > threshold 0.02 → reject `leg_spread_too_wide`."""
    yes_book = _book(ask=0.65, bid=0.61)   # spread 0.04
    no_book = _book(ask=0.35, bid=0.34)    # spread 0.01
    m = _market_with_seconds_left(yes_book, no_book)

    async def _fake_get_book(token_id: str):
        return yes_book if token_id == "yes_tok" else no_book

    monkeypatch.setattr(lev3.pm, "get_book", _fake_get_book)

    cand, reason = await lev3._evaluate_market(m, **_evaluate_args(max_leg_spread=0.02))
    assert cand is None
    assert reason == "leg_spread_too_wide"


@pytest.mark.asyncio
async def test_evaluate_market_rejects_when_no_leg_spread_too_wide(monkeypatch):
    """NO leg ask-bid = 0.04 > threshold 0.02 → reject `leg_spread_too_wide`."""
    yes_book = _book(ask=0.65, bid=0.64)   # spread 0.01
    no_book = _book(ask=0.35, bid=0.31)    # spread 0.04
    m = _market_with_seconds_left(yes_book, no_book)

    async def _fake_get_book(token_id: str):
        return yes_book if token_id == "yes_tok" else no_book

    monkeypatch.setattr(lev3.pm, "get_book", _fake_get_book)

    cand, reason = await lev3._evaluate_market(m, **_evaluate_args(max_leg_spread=0.02))
    assert cand is None
    assert reason == "leg_spread_too_wide"


@pytest.mark.asyncio
async def test_evaluate_market_accepts_when_both_legs_tight(monkeypatch):
    """Both leg spreads ≤ threshold → candidate proceeds (no rejection
    on the spread gate; downstream gates may or may not fire)."""
    yes_book = _book(ask=0.65, bid=0.64)   # spread 0.01
    no_book = _book(ask=0.35, bid=0.34)    # spread 0.01
    m = _market_with_seconds_left(yes_book, no_book)

    async def _fake_get_book(token_id: str):
        return yes_book if token_id == "yes_tok" else no_book

    monkeypatch.setattr(lev3.pm, "get_book", _fake_get_book)

    cand, reason = await lev3._evaluate_market(m, **_evaluate_args(max_leg_spread=0.02))
    # The spread gate must NOT be the reason for any rejection here.
    assert reason != "leg_spread_too_wide"
    # And when accepted, the candidate metadata must surface the per-leg
    # spreads for downstream observability.
    if cand is not None:
        assert cand.metadata["leg_spread_yes"] == pytest.approx(0.01)
        assert cand.metadata["leg_spread_no"] == pytest.approx(0.01)


@pytest.mark.asyncio
async def test_evaluate_market_no_op_when_max_leg_spread_none(monkeypatch):
    """safe_close + flip_hunter pass max_leg_spread=None → even very wide
    per-leg spreads must NOT trigger the gate (other gates apply)."""
    yes_book = _book(ask=0.65, bid=0.20)   # spread 0.45
    no_book = _book(ask=0.35, bid=0.05)    # spread 0.30
    m = _market_with_seconds_left(yes_book, no_book)

    async def _fake_get_book(token_id: str):
        return yes_book if token_id == "yes_tok" else no_book

    monkeypatch.setattr(lev3.pm, "get_book", _fake_get_book)

    cand, reason = await lev3._evaluate_market(m, **_evaluate_args(max_leg_spread=None))
    # Whatever the outcome, the per-leg spread gate did not fire.
    assert reason != "leg_spread_too_wide"
    assert reason != "leg_spread_missing_bid"


@pytest.mark.asyncio
async def test_evaluate_market_disable_sentinel_is_zero(monkeypatch):
    """max_leg_spread=0 must disable the gate (escape hatch parity with
    the runtime `> 0` branch in the code)."""
    yes_book = _book(ask=0.65, bid=0.20)   # spread 0.45 — would reject if gate live
    no_book = _book(ask=0.35, bid=0.05)
    m = _market_with_seconds_left(yes_book, no_book)

    async def _fake_get_book(token_id: str):
        return yes_book if token_id == "yes_tok" else no_book

    monkeypatch.setattr(lev3.pm, "get_book", _fake_get_book)

    cand, reason = await lev3._evaluate_market(m, **_evaluate_args(max_leg_spread=0.0))
    assert reason != "leg_spread_too_wide", (
        "Disable sentinel broken: max_leg_spread=0 must skip the gate."
    )


@pytest.mark.asyncio
async def test_evaluate_market_accepts_exact_boundary_spread(monkeypatch):
    """IEEE-754 trap regression: ``0.65 - 0.63`` evaluates to
    ``0.020000000000000018`` which strictly > 0.02. Without rounding to
    a sub-tick precision, a market with an exact 0.02-spread leg gets
    falsely rejected as `leg_spread_too_wide`. Polymarket tick is 0.01
    so 4-decimal rounding preserves accuracy while killing the float
    artifact."""
    yes_book = _book(ask=0.65, bid=0.63)   # exact 0.02 spread (or 0.020000000000000018 raw)
    no_book = _book(ask=0.35, bid=0.34)    # spread 0.01
    m = _market_with_seconds_left(yes_book, no_book)

    async def _fake_get_book(token_id: str):
        return yes_book if token_id == "yes_tok" else no_book

    monkeypatch.setattr(lev3.pm, "get_book", _fake_get_book)

    cand, reason = await lev3._evaluate_market(m, **_evaluate_args(max_leg_spread=0.02))
    assert reason != "leg_spread_too_wide", (
        "IEEE-754 false-reject regression: exact 0.02 boundary spread "
        f"got rejected as too wide (raw subtraction = {0.65 - 0.63!r})."
    )


@pytest.mark.asyncio
async def test_evaluate_market_rejects_when_bid_missing(monkeypatch):
    """If a leg has no bid at all the gate cannot evaluate the spread;
    rejecting `leg_spread_missing_bid` is safer than letting it through
    (no bid = no-one wants to buy = an even worse fill scenario)."""
    yes_book = {"asks": [{"price": "0.65", "size": "100"}], "bids": []}
    no_book = _book(ask=0.35, bid=0.34)
    m = _market_with_seconds_left(yes_book, no_book)

    async def _fake_get_book(token_id: str):
        return yes_book if token_id == "yes_tok" else no_book

    monkeypatch.setattr(lev3.pm, "get_book", _fake_get_book)

    cand, reason = await lev3._evaluate_market(m, **_evaluate_args(max_leg_spread=0.02))
    assert cand is None
    assert reason == "leg_spread_missing_bid"
