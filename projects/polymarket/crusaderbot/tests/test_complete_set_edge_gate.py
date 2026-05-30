"""Regression: complete-set edge gate (WARP/R00T/complete-set-edge-gate).

Promotes the Lane 3 observational metric (PR #1477,
``test_complete_set_edge_metric.py``) to a hard entry reject. When
``_process_candidate`` receives a late_entry_v3 candidate whose
``metadata["complete_set_edge"] < config.MIN_COMPLETE_SET_EDGE`` (default
0.005 = 50 bps), the candidate is rejected with
``scan_outcome="skipped_negative_arb"`` BEFORE the live-price fetch.

Why: Polymarket binary UP/DOWN tokens settle to $1.00 at expiry, so
``cost = ask_UP + ask_DOWN`` is the spot arb bound. Entering a single
side when the complete-set is already at or above the bound = directional
bet at full price after fees, no arb safety net (directive 1.1).

Scope:
  - Only candidates that carry ``metadata["complete_set_edge"]``
    (late_entry_v3 presets: close_sweep / safe_close / flip_hunter) are
    gated.
  - Strategies that omit the stamp (signal_following / momentum /
    copy_trade) pass through cleanly — no-op.

Knob:
  - ``config.MIN_COMPLETE_SET_EDGE=0`` disables the gate (escape hatch).
  - Negative / non-finite values rejected at config load.

Guard lives in:
  ``services.signal_scan.signal_scan_job._process_candidate`` step 3b-0a
Stamp lives in:
  ``domain.strategy.strategies.late_entry_v3._evaluate_market``
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
from projects.polymarket.crusaderbot.domain.strategy.strategies import (
    late_entry_v3 as lev3,
)
from projects.polymarket.crusaderbot.domain.strategy.types import SignalCandidate
from projects.polymarket.crusaderbot.services.signal_scan import (
    signal_scan_job as ssj,
)
from projects.polymarket.crusaderbot.services.trade_engine import TradeResult


_USER_UUID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
_MARKET_ID = "cs-edge-gate-market"


@pytest.fixture(autouse=True)
def _reset_registry():
    StrategyRegistry._reset_for_tests()
    yield
    StrategyRegistry._reset_for_tests()


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    crusaderbot_config.get_settings.cache_clear()
    yield
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
# Source-level pins — fail closed if the guard is removed or scope is broken.
# ---------------------------------------------------------------------


def test_process_candidate_has_complete_set_edge_gate():
    """`_process_candidate` must contain the `skipped_negative_arb` outcome
    path; if removed, late_entry_v3 candidates will fire even when the
    complete-set cost has reached or exceeded the $1.00 settlement bound.
    """
    src = inspect.getsource(ssj._process_candidate)
    assert "skipped_negative_arb" in src, (
        "Regression: _process_candidate lost its complete-set edge gate."
    )


def test_process_candidate_reads_config_knob():
    """The gate must read the `MIN_COMPLETE_SET_EDGE` config knob (not a
    hard-coded literal) so the operator can disable / retune without
    redeploy.
    """
    src = inspect.getsource(ssj._process_candidate)
    assert "MIN_COMPLETE_SET_EDGE" in src, (
        "Regression: complete-set edge gate must read "
        "config.MIN_COMPLETE_SET_EDGE."
    )


def test_process_candidate_gate_scoped_to_stamped_candidates():
    """Gate must be conditional on `metadata['complete_set_edge']` so
    candidates that don't carry the stamp (signal_following, momentum,
    copy_trade) bypass it cleanly. A global gate would block every
    non-late_entry_v3 strategy.
    """
    src = inspect.getsource(ssj._process_candidate)
    assert 'cand.metadata.get("complete_set_edge")' in src, (
        "Regression: complete-set edge gate must be scoped to candidates "
        "carrying metadata['complete_set_edge']; a global gate breaks "
        "signal_following / momentum / copy_trade."
    )


def test_late_entry_v3_stamps_complete_set_edge():
    """`_evaluate_market` must stamp `complete_set_edge` into the candidate
    metadata so `_process_candidate` has a basis to gate the entry.
    Removing the stamp would silently disable the gate for every
    late_entry_v3 preset (close_sweep / safe_close / flip_hunter).
    """
    src = inspect.getsource(lev3._evaluate_market)
    assert "complete_set_edge" in src, (
        "Regression: late_entry_v3._evaluate_market lost the "
        "complete_set_edge stamp — gate is now a no-op for close_sweep / "
        "safe_close / flip_hunter."
    )


def test_disable_sentinel_is_zero():
    """Operator must be able to disable the gate (revert to pre-lane
    behaviour) via MIN_COMPLETE_SET_EDGE=0 without redeploy. The gate
    code branches on `> 0` so 0 is the disable sentinel.
    """
    src = inspect.getsource(ssj._process_candidate)
    assert "_min_edge > 0" in src, (
        "Regression: complete-set edge gate must short-circuit when "
        "MIN_COMPLETE_SET_EDGE=0 (operator escape hatch)."
    )


# ---------------------------------------------------------------------
# Config knob — defaults + validators + escape hatch.
# ---------------------------------------------------------------------


def test_min_complete_set_edge_default_is_50bps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default matches the directive (50bps): covers Polymarket maker/taker
    fees + thin buffer above pure arb breakeven."""
    _set_required_env(monkeypatch)
    monkeypatch.delenv("MIN_COMPLETE_SET_EDGE", raising=False)
    s = crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert s.MIN_COMPLETE_SET_EDGE == 0.005


def test_min_complete_set_edge_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Operator must be able to retune / disable the gate via env without
    redeploy; pydantic-settings picks up MIN_COMPLETE_SET_EDGE from env.
    """
    _set_required_env(monkeypatch)
    monkeypatch.setenv("MIN_COMPLETE_SET_EDGE", "0")
    s = crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert s.MIN_COMPLETE_SET_EDGE == 0


@pytest.mark.parametrize("bad", ["-0.01", "nan", "inf", "-inf"])
def test_min_complete_set_edge_rejects_invalid(
    monkeypatch: pytest.MonkeyPatch, bad: str,
) -> None:
    """Negative + non-finite MIN_COMPLETE_SET_EDGE must fail at config load.
    Both would silently disable the gate at runtime (the check is
    `metric < threshold`; `metric < NaN` is always False, `metric < -1` is
    always False) — exactly the trap the gate exists to prevent."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("MIN_COMPLETE_SET_EDGE", bad)
    with pytest.raises(Exception) as excinfo:
        crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert "MIN_COMPLETE_SET_EDGE" in str(excinfo.value)


# ---------------------------------------------------------------------
# Behavioural integration — call _process_candidate end-to-end with the
# upstream/downstream dependencies mocked to the same surface as
# test_tob_freshness_gate.py.
# ---------------------------------------------------------------------


def _user_row() -> dict:
    return {
        "user_id": _USER_UUID,
        "telegram_user_id": 43,
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
    }


def _market_row() -> dict:
    # No "updown" in slug so the sub-cent guard (step 3b-i) does not
    # interfere with the edge gate (step 3b-0a) being tested here.
    return {
        "id": _MARKET_ID,
        "slug": "cs-edge-gate-market",
        "question": "Will X happen?",
        "status": "active",
        "yes_price": 0.65,
        "no_price": 0.35,
        "yes_token_id": "tok_yes",
        "no_token_id": "tok_no",
        "liquidity_usdc": 20000.0,
    }


def _late_entry_candidate(
    *,
    complete_set_edge: float | None,
    entry_price: float = 0.65,
    fresh_ts: bool = True,
) -> SignalCandidate:
    md: dict = {
        "market_id": _MARKET_ID,
        "entry_price": entry_price,
        "fav_price_min": 0.60,
        "fav_price_max": 0.70,
        "underdog_mode": False,
    }
    if complete_set_edge is not None:
        md["complete_set_edge"] = complete_set_edge
    if fresh_ts:
        # Fresh entry_price_ts so the TOB freshness gate (step 3b-0) does
        # not interfere — we're isolating the edge gate's behaviour.
        md["entry_price_ts"] = datetime.now(timezone.utc).timestamp()
    return SignalCandidate(
        market_id=_MARKET_ID,
        condition_id=_MARKET_ID,
        side="YES",
        confidence=0.7,
        suggested_size_usdc=10.0,
        strategy_name="late_entry_v3",
        signal_ts=datetime.now(timezone.utc),
        metadata=md,
    )


def _signal_following_candidate() -> SignalCandidate:
    # No complete_set_edge stamp — represents signal_following / momentum /
    # copy_trade. The edge gate MUST no-op for these.
    return SignalCandidate(
        market_id=_MARKET_ID,
        condition_id=_MARKET_ID,
        side="YES",
        confidence=0.7,
        suggested_size_usdc=10.0,
        strategy_name="signal_following",
        signal_ts=datetime.now(timezone.utc),
        metadata={
            "feed_id": str(uuid4()),
            "publication_id": str(uuid4()),
            "market_id": _MARKET_ID,
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


def _run_process_candidate(
    *,
    row: dict,
    cand: SignalCandidate,
    fill_price: float = 0.66,
) -> bool:
    """Drive `_process_candidate` with upstream/downstream mocks; return
    True iff the trade engine was actually reached.
    """
    engine_called = {"called": False}

    async def _track_execute(signal):
        engine_called["called"] = True
        return _approved_trade_result()

    with patch.object(ssj, "_load_stale_queued_row", return_value=None), \
            patch.object(ssj, "_publication_already_queued", return_value=False), \
            patch.object(ssj, "_has_open_position_for_market", return_value=False), \
            patch.object(ssj, "_load_market", return_value=_market_row()), \
            patch.object(ssj, "get_live_market_price",
                         new=AsyncMock(return_value=fill_price)), \
            patch.object(ssj._engine, "execute", side_effect=_track_execute), \
            patch.object(ssj, "_insert_execution_queue", return_value=True), \
            patch.object(ssj, "_mark_executed", new=AsyncMock()):
        asyncio.run(ssj._process_candidate(row, cand))
    return engine_called["called"]


def test_negative_arb_late_entry_candidate_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A late_entry_v3 candidate with `complete_set_edge = -0.01` (cost
    above the $1.00 settlement bound) MUST short-circuit at the edge gate
    — the trade engine must never be called. Validates the gate's `<`
    operator: if a future edit flipped the comparison the engine would
    fire and this asserts.
    """
    _set_required_env(monkeypatch)
    monkeypatch.setenv("MIN_COMPLETE_SET_EDGE", "0.005")
    bootstrap_default_strategies()

    cand = _late_entry_candidate(complete_set_edge=-0.01)

    reached_engine = _run_process_candidate(row=_user_row(), cand=cand)
    assert not reached_engine, (
        "Late_entry_v3 candidate with edge=-0.01 (below 0.005 threshold) "
        "must be rejected at step 3b-0a before reaching the trade engine."
    )


def test_marginal_edge_candidate_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A candidate with `complete_set_edge = 0.001` (positive but below
    the 50bps threshold) MUST be rejected. Defends against the 'edge
    illusion' failure mode (Appendix C): tiny positive edge eaten by fees
    + slippage.
    """
    _set_required_env(monkeypatch)
    monkeypatch.setenv("MIN_COMPLETE_SET_EDGE", "0.005")
    bootstrap_default_strategies()

    cand = _late_entry_candidate(complete_set_edge=0.001)

    reached_engine = _run_process_candidate(row=_user_row(), cand=cand)
    assert not reached_engine, (
        "Marginal candidate (edge=0.001 < 0.005 threshold) must be "
        "rejected at the complete-set edge gate."
    )


def test_strong_edge_candidate_reaches_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A late_entry_v3 candidate with `complete_set_edge = 0.03` (300 bps,
    well above the 50 bps threshold) MUST pass the edge gate and reach
    the engine. Validates the gate is not over-eager.
    """
    _set_required_env(monkeypatch)
    monkeypatch.setenv("MIN_COMPLETE_SET_EDGE", "0.005")
    bootstrap_default_strategies()

    cand = _late_entry_candidate(complete_set_edge=0.03)

    reached_engine = _run_process_candidate(row=_user_row(), cand=cand)
    assert reached_engine, (
        "Strong candidate (edge=0.03 > 0.005 threshold) must pass the "
        "complete-set edge gate and reach the trade engine."
    )


def test_disabled_gate_passes_negative_arb_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Operator escape hatch: with `MIN_COMPLETE_SET_EDGE=0` even a
    negative-arb candidate MUST reach the engine (the gate is fully
    disabled — revert to pre-lane behaviour without redeploy).
    """
    _set_required_env(monkeypatch)
    monkeypatch.setenv("MIN_COMPLETE_SET_EDGE", "0")
    bootstrap_default_strategies()

    cand = _late_entry_candidate(complete_set_edge=-0.05)

    reached_engine = _run_process_candidate(row=_user_row(), cand=cand)
    assert reached_engine, (
        "Disable sentinel broken: MIN_COMPLETE_SET_EDGE=0 must skip the "
        "gate and allow even negative-arb candidates through (operator "
        "escape hatch)."
    )


def test_candidate_without_stamp_bypasses_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scope assertion: a signal_following candidate that carries NO
    `complete_set_edge` MUST pass the edge gate (no-op for strategies
    that don't stamp the metric). A regression that made the gate
    global would break every non-late_entry_v3 strategy.
    """
    _set_required_env(monkeypatch)
    monkeypatch.setenv("MIN_COMPLETE_SET_EDGE", "0.005")
    bootstrap_default_strategies()

    cand = _signal_following_candidate()  # no complete_set_edge

    reached_engine = _run_process_candidate(row=_user_row(), cand=cand)
    assert reached_engine, (
        "Candidates without complete_set_edge must bypass the gate — "
        "signal_following / momentum / copy_trade cannot afford a global "
        "gate that breaks their normal path."
    )


def test_boundary_at_threshold_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Boundary test: edge exactly equal to threshold MUST pass (the gate
    is `< threshold`, not `<= threshold`). Pins the operator-friendly
    convention that the threshold is the minimum acceptable, not the
    minimum rejected.
    """
    _set_required_env(monkeypatch)
    monkeypatch.setenv("MIN_COMPLETE_SET_EDGE", "0.005")
    bootstrap_default_strategies()

    cand = _late_entry_candidate(complete_set_edge=0.005)

    reached_engine = _run_process_candidate(row=_user_row(), cand=cand)
    assert reached_engine, (
        "Edge exactly at threshold (0.005 == 0.005) must pass — gate "
        "uses `<` not `<=`."
    )
