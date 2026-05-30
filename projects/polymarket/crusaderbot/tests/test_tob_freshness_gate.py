"""Regression: TOB freshness gate (WARP/R00T/tob-freshness-gate).

Defense layer over the existing sub-cent / Gamma-fallback guard
(`test_flip_hunter_stale_price_fix.py`). When `_process_candidate` receives
a late_entry_v3 candidate whose orderbook snapshot is older than
`config.TOB_STALE_MS` (default 2000ms), the candidate is rejected with
`scan_outcome="skipped_stale_tob"` instead of being fired against a stale
live mark.

Scope:
  - Only candidates that carry `metadata["entry_price_ts"]` (late_entry_v3
    presets: close_sweep / safe_close / flip_hunter) are gated.
  - Strategies that omit the stamp (signal_following, momentum, copy_trade)
    pass through cleanly — no-op.

Knob:
  - `config.TOB_STALE_MS=0` disables the gate (escape hatch).

Guard lives in:
  ``services.signal_scan.signal_scan_job._process_candidate`` step 3b-0
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


_USER_UUID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
_MARKET_ID = "tob-gate-market"


@pytest.fixture(autouse=True)
def _reset_registry():
    StrategyRegistry._reset_for_tests()
    yield
    StrategyRegistry._reset_for_tests()


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


def test_process_candidate_has_tob_freshness_gate():
    """`_process_candidate` must contain the `skipped_stale_tob` outcome
    path; if removed, late_entry_v3 candidates will fire on stale CLOB
    snapshots when the scheduler back-pressures.
    """
    src = inspect.getsource(ssj._process_candidate)
    assert "skipped_stale_tob" in src, (
        "Regression: _process_candidate lost its TOB freshness gate."
    )


def test_process_candidate_reads_config_knob():
    """The gate must read the `TOB_STALE_MS` config knob (not a hard-coded
    literal) so the operator can disable / retune without redeploy.
    """
    src = inspect.getsource(ssj._process_candidate)
    assert "TOB_STALE_MS" in src, (
        "Regression: TOB freshness gate must read config.TOB_STALE_MS."
    )


def test_process_candidate_gate_scoped_to_stamped_candidates():
    """Gate must be conditional on `metadata['entry_price_ts']` so
    candidates that don't carry the stamp (signal_following, momentum,
    copy_trade) bypass it cleanly. A global gate would block every
    non-late_entry_v3 strategy.
    """
    src = inspect.getsource(ssj._process_candidate)
    assert 'cand.metadata.get("entry_price_ts")' in src, (
        "Regression: TOB freshness gate must be scoped to candidates "
        "carrying metadata['entry_price_ts']; a global gate breaks "
        "signal_following / momentum / copy_trade."
    )


def test_late_entry_v3_stamps_entry_price_ts():
    """`_evaluate_market` must stamp `entry_price_ts` into the candidate
    metadata so `_process_candidate` has a basis to measure staleness.
    Removing the stamp would silently disable the gate for every
    late_entry_v3 preset (close_sweep / safe_close / flip_hunter).
    """
    src = inspect.getsource(lev3._evaluate_market)
    assert "entry_price_ts" in src, (
        "Regression: late_entry_v3._evaluate_market lost the "
        "entry_price_ts stamp — TOB freshness gate is now a no-op for "
        "close_sweep / safe_close / flip_hunter."
    )


# ---------------------------------------------------------------------
# Config knob — defaults + escape hatch.
# ---------------------------------------------------------------------


def test_tob_stale_ms_default_is_2000(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default matches Polybot research reference: snapshots older than
    2s have materially diverged from the live mark."""
    _set_required_env(monkeypatch)
    monkeypatch.delenv("TOB_STALE_MS", raising=False)
    s = crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert s.TOB_STALE_MS == 2000
    crusaderbot_config.get_settings.cache_clear()


def test_tob_stale_ms_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Operator must be able to retune / disable the gate via env without
    redeploy; pydantic-settings picks up TOB_STALE_MS from the environment."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("TOB_STALE_MS", "0")
    s = crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert s.TOB_STALE_MS == 0
    crusaderbot_config.get_settings.cache_clear()


def test_tob_stale_ms_disable_sentinel_is_zero():
    """Operator must be able to disable the gate (revert to pre-lane
    behaviour) via TOB_STALE_MS=0 without redeploy. The gate code
    branches on `> 0` so 0 is the disable sentinel."""
    src = inspect.getsource(ssj._process_candidate)
    assert "_tob_stale_ms > 0" in src, (
        "Regression: TOB freshness gate must short-circuit when "
        "TOB_STALE_MS=0 (operator escape hatch)."
    )


# ---------------------------------------------------------------------
# Behavioural integration — call _process_candidate end-to-end with the
# upstream/downstream dependencies mocked to the same surface as the
# existing band-gate tests (test_signal_scan_job.py). The gate's correct
# operator (`>`) and its scope (stamped-only) are exercised by observing
# whether the trade engine is reached.
# ---------------------------------------------------------------------


def _user_row() -> dict:
    return {
        "user_id": _USER_UUID,
        "telegram_user_id": 42,
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
    # interfere with the freshness gate (step 3b-0) being tested here.
    return {
        "id": _MARKET_ID,
        "slug": "tob-gate-market",
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
    entry_price_ts: float | None,
    entry_price: float = 0.65,
) -> SignalCandidate:
    md: dict = {
        "market_id": _MARKET_ID,
        "entry_price": entry_price,
        "fav_price_min": 0.60,
        "fav_price_max": 0.70,
        "underdog_mode": False,
    }
    if entry_price_ts is not None:
        md["entry_price_ts"] = entry_price_ts
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
    # No entry_price_ts stamp — represents signal_following / momentum /
    # copy_trade. The freshness gate MUST no-op for these.
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


def test_stale_late_entry_candidate_is_rejected_before_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A late_entry_v3 candidate with `entry_price_ts` 3s old (threshold
    2000ms) MUST short-circuit at the freshness gate — the trade engine
    must never be called. Validates the gate's `>` operator: if a future
    edit flipped the comparison the engine would fire and this asserts.
    """
    _set_required_env(monkeypatch)
    monkeypatch.setenv("TOB_STALE_MS", "2000")
    crusaderbot_config.get_settings.cache_clear()
    bootstrap_default_strategies()

    now_ts = datetime.now(timezone.utc).timestamp()
    cand = _late_entry_candidate(entry_price_ts=now_ts - 3.0)

    reached_engine = _run_process_candidate(row=_user_row(), cand=cand)
    assert not reached_engine, (
        "Stale late_entry_v3 candidate (3s old > 2000ms threshold) must "
        "be rejected at step 3b-0 before reaching the trade engine."
    )
    crusaderbot_config.get_settings.cache_clear()


def test_fresh_late_entry_candidate_reaches_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A late_entry_v3 candidate with `entry_price_ts` 500ms old MUST
    pass the freshness gate and reach the engine (downstream gates also
    mocked to pass). Validates the gate is not over-eager.
    """
    _set_required_env(monkeypatch)
    monkeypatch.setenv("TOB_STALE_MS", "2000")
    crusaderbot_config.get_settings.cache_clear()
    bootstrap_default_strategies()

    now_ts = datetime.now(timezone.utc).timestamp()
    cand = _late_entry_candidate(entry_price_ts=now_ts - 0.5)

    reached_engine = _run_process_candidate(row=_user_row(), cand=cand)
    assert reached_engine, (
        "Fresh late_entry_v3 candidate (500ms old < 2000ms threshold) "
        "must pass the freshness gate and reach the trade engine."
    )
    crusaderbot_config.get_settings.cache_clear()


def test_disabled_gate_passes_stale_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Operator escape hatch: with `TOB_STALE_MS=0` a stale candidate
    MUST still reach the engine (the gate is fully disabled — revert to
    pre-lane behaviour without redeploy).
    """
    _set_required_env(monkeypatch)
    monkeypatch.setenv("TOB_STALE_MS", "0")
    crusaderbot_config.get_settings.cache_clear()
    bootstrap_default_strategies()

    now_ts = datetime.now(timezone.utc).timestamp()
    cand = _late_entry_candidate(entry_price_ts=now_ts - 60.0)  # 60s old

    reached_engine = _run_process_candidate(row=_user_row(), cand=cand)
    assert reached_engine, (
        "Disable sentinel broken: TOB_STALE_MS=0 must skip the gate and "
        "allow even very-stale candidates through (operator escape hatch)."
    )
    crusaderbot_config.get_settings.cache_clear()


def test_candidate_without_stamp_bypasses_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scope assertion: a signal_following candidate that carries NO
    `entry_price_ts` MUST pass the freshness gate (no-op for strategies
    that don't stamp the snapshot time). A regression that made the gate
    global would break every non-late_entry_v3 strategy.
    """
    _set_required_env(monkeypatch)
    monkeypatch.setenv("TOB_STALE_MS", "2000")
    crusaderbot_config.get_settings.cache_clear()
    bootstrap_default_strategies()

    cand = _signal_following_candidate()  # no entry_price_ts

    # signal_following doesn't carry entry_price → fill resolves via
    # get_live_market_price (mocked to 0.66, inside any reasonable band).
    reached_engine = _run_process_candidate(row=_user_row(), cand=cand)
    assert reached_engine, (
        "Candidates without entry_price_ts must bypass the freshness "
        "gate — signal_following / momentum / copy_trade cannot afford "
        "a global gate that breaks their normal path."
    )
    crusaderbot_config.get_settings.cache_clear()
