"""Safe-close per-(user, side) direction concentration limit
(WARP/R00T/safe-close-direction-limit, Lane 4/5 Polybot directive).

Rationale: late_entry_v3 chooses side dynamically per scan
(`fav_side = "YES" if yes_ask > no_ask else "NO"`), so there is no
per-candle directional bias. But in a trending market the same side
ends up favoured candle after candle — the bot then aggregates
directional risk that the per-candle filter never sees. This gate caps
that aggregate at ``SAFE_CLOSE_DIRECTION_LIMIT_PER_HOUR`` per
(user, side) within a rolling 1h window.

Scope discipline:
  - Only fires when ``row["active_preset"] == "safe_close"``.
  - close_sweep / flip_hunter / signal_following / copy_trade bypass.
  - Per-user (multi-tenant): User A's NO count does not affect User B.
  - Per-side: a user's YES count does not affect their NO eligibility.

Escape hatch: ``SAFE_CLOSE_DIRECTION_LIMIT_PER_HOUR=0`` disables (runtime
branches on `> 0`). Negative values rejected at config load.

Gate / record lives in:
  ``services.signal_scan.signal_scan_job._process_candidate`` step 3d.
Window state + helpers live in:
  ``services.signal_scan.signal_scan_job`` module level.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from projects.polymarket.crusaderbot import config as crusaderbot_config
from projects.polymarket.crusaderbot.domain.strategy import (
    StrategyRegistry,
    bootstrap_default_strategies,
)
from projects.polymarket.crusaderbot.domain.strategy.types import SignalCandidate
from projects.polymarket.crusaderbot.services.signal_scan import (
    signal_scan_job as ssj,
)
from projects.polymarket.crusaderbot.services.trade_engine import TradeResult


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("OPERATOR_CHAT_ID", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("WALLET_HD_SEED", "seed")
    monkeypatch.setenv("WALLET_ENCRYPTION_KEY", "k")
    monkeypatch.setenv("POLYGON_RPC_URL", "https://rpc")
    monkeypatch.setenv("ALCHEMY_POLYGON_WS_URL", "wss://ws")


@pytest.fixture(autouse=True)
def _isolated_state():
    """Reset both StrategyRegistry and the in-process safe_close window
    between tests — otherwise leftover entries from one test would
    skew the count visible to the next."""
    StrategyRegistry._reset_for_tests()
    ssj._safe_close_reset_for_tests()
    crusaderbot_config.get_settings.cache_clear()
    yield
    StrategyRegistry._reset_for_tests()
    ssj._safe_close_reset_for_tests()
    crusaderbot_config.get_settings.cache_clear()


# ---------------------------------------------------------------------
# Window helper — count / record / prune semantics.
# ---------------------------------------------------------------------


def test_recent_count_empty_returns_zero():
    """Fresh window for a (user, side) key returns 0."""
    now = datetime.now(timezone.utc).timestamp()
    assert ssj._safe_close_recent_count("user-A", "YES", now) == 0
    assert ssj._safe_close_recent_count("user-A", "NO", now) == 0


def test_record_then_count_increments():
    """A recorded entry shows up in the count for the same (user, side)
    and only that key."""
    now = datetime.now(timezone.utc).timestamp()
    ssj._safe_close_record_entry("user-A", "YES", now)
    assert ssj._safe_close_recent_count("user-A", "YES", now) == 1
    # Sibling side is independent.
    assert ssj._safe_close_recent_count("user-A", "NO", now) == 0
    # Sibling user is independent.
    assert ssj._safe_close_recent_count("user-B", "YES", now) == 0


def test_side_normalization_is_case_insensitive():
    """`yes` and `YES` must collide — the gate compares uppercase."""
    now = datetime.now(timezone.utc).timestamp()
    ssj._safe_close_record_entry("user-A", "yes", now)
    assert ssj._safe_close_recent_count("user-A", "YES", now) == 1
    assert ssj._safe_close_recent_count("user-A", "yes", now) == 1


def test_window_prunes_entries_older_than_1h():
    """Entries older than the configured window are evicted on read."""
    now = datetime.now(timezone.utc).timestamp()
    # Two old (90 min ago) + two recent (30 min ago).
    for t in [now - 5400, now - 5400, now - 1800, now - 1800]:
        ssj._safe_close_record_entry("user-A", "YES", t)
    # Reading at `now` evicts the two old entries.
    assert ssj._safe_close_recent_count("user-A", "YES", now) == 2


def test_window_boundary_exactly_1h_kept():
    """Entry exactly at the cutoff boundary must NOT be evicted (the
    prune predicate uses `>= cutoff`, not `>`)."""
    now = datetime.now(timezone.utc).timestamp()
    ssj._safe_close_record_entry("user-A", "YES", now - 3600.0)
    assert ssj._safe_close_recent_count("user-A", "YES", now) == 1


def test_empty_keys_removed_after_full_prune():
    """Memory hygiene: when all entries for a (user, side) key expire,
    the dict key itself must be deleted — otherwise the log grows
    monotonically with rotating user IDs and inactive-user fossils."""
    now = datetime.now(timezone.utc).timestamp()
    ssj._safe_close_record_entry("user-A", "YES", now - 7200.0)  # 2h ago
    ssj._safe_close_record_entry("user-A", "YES", now - 7200.0)
    assert ("user-A", "YES") in ssj._safe_close_direction_log
    # Reading at `now` prunes all 2h-old entries → list empties → key
    # must be removed.
    assert ssj._safe_close_recent_count("user-A", "YES", now) == 0
    assert ("user-A", "YES") not in ssj._safe_close_direction_log


def test_recent_count_does_not_create_empty_key():
    """A read on a never-recorded (user, side) must not leave an empty
    list behind — same memory-hygiene contract as the prune path."""
    now = datetime.now(timezone.utc).timestamp()
    assert ssj._safe_close_recent_count("user-NEW", "YES", now) == 0
    assert ("user-NEW", "YES") not in ssj._safe_close_direction_log


# ---------------------------------------------------------------------
# Config knob — default + env override + negative rejection.
# ---------------------------------------------------------------------


def test_default_limit_is_8(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.delenv("SAFE_CLOSE_DIRECTION_LIMIT_PER_HOUR", raising=False)
    s = crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert s.SAFE_CLOSE_DIRECTION_LIMIT_PER_HOUR == 8


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("SAFE_CLOSE_DIRECTION_LIMIT_PER_HOUR", "20")
    s = crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert s.SAFE_CLOSE_DIRECTION_LIMIT_PER_HOUR == 20


def test_disable_sentinel_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("SAFE_CLOSE_DIRECTION_LIMIT_PER_HOUR", "0")
    s = crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert s.SAFE_CLOSE_DIRECTION_LIMIT_PER_HOUR == 0


def test_negative_rejected_at_load(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same trap as the other guardrail knobs: -1 would silently
    disable the gate the same as 0 because runtime branches on `> 0`."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("SAFE_CLOSE_DIRECTION_LIMIT_PER_HOUR", "-1")
    with pytest.raises(ValidationError) as excinfo:
        crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert "SAFE_CLOSE_DIRECTION_LIMIT_PER_HOUR" in str(excinfo.value)


# ---------------------------------------------------------------------
# Behavioural — gate in _process_candidate.
# ---------------------------------------------------------------------


_USER_UUID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


def _user_row(*, active_preset: str = "safe_close") -> dict:
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
        "active_preset": active_preset,
    }


def _market_row() -> dict:
    return {
        "id": "market-001",
        "slug": "btc-no-updown-test",
        "question": "Will X happen?",
        "status": "active",
        "yes_price": 0.55,
        "no_price": 0.45,
        "yes_token_id": "tok_yes",
        "no_token_id": "tok_no",
        "liquidity_usdc": 20000.0,
    }


def _late_entry_candidate(side: str = "YES") -> SignalCandidate:
    """Mirrors the band-gate test pattern — late_entry_v3 candidate
    that bypasses the band gate (entry_price within fav_price_min/max
    range) so the test reaches the direction-concentration gate."""
    return SignalCandidate(
        market_id="market-001",
        condition_id="market-001",
        side=side,
        confidence=0.7,
        suggested_size_usdc=10.0,
        strategy_name="late_entry_v3",
        signal_ts=datetime.now(timezone.utc),
        metadata={
            "market_id": "market-001",
            "entry_price": 0.65,
            "fav_price_min": 0.60,
            "fav_price_max": 0.70,
            "underdog_mode": False,
        },
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
        final_size_usdc=Decimal("10"),
    )


def _run(
    *,
    row: dict,
    cand: SignalCandidate,
    execute=None,
    insert_returns: bool = True,
) -> bool:
    """Drive `_process_candidate` with the full mock stack and return
    True iff `_engine.execute` was reached (i.e. the gate did not
    short-circuit).

    `execute`: optional async callable to patch in as the engine's
    `execute`. Defaults to a tracker that records the call and returns
    `_approved_result()`. Callers that need a different result shape
    (e.g. mode='duplicate') pass their own coroutine.

    `insert_returns`: value to make `_insert_execution_queue` return.
    Callers test the concurrent-tick ON CONFLICT path by passing False.
    """
    engine_called = {"called": False}

    async def _track_execute(signal):
        engine_called["called"] = True
        return _approved_result()

    exec_fn = execute or _track_execute
    with patch.object(ssj, "_load_stale_queued_row", return_value=None), \
            patch.object(ssj, "_publication_already_queued", return_value=False), \
            patch.object(ssj, "_has_open_position_for_market", return_value=False), \
            patch.object(ssj, "_load_market", return_value=_market_row()), \
            patch.object(ssj, "get_live_market_price",
                         new=AsyncMock(return_value=0.66)), \
            patch.object(ssj._engine, "execute", side_effect=exec_fn), \
            patch.object(ssj, "_insert_execution_queue", return_value=insert_returns), \
            patch.object(ssj, "_mark_executed", new=AsyncMock()):
        asyncio.run(ssj._process_candidate(row, cand))
    return engine_called["called"]


def test_gate_blocks_when_user_at_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """User with N prior safe_close YES entries (where N == limit) MUST
    have the (N+1)-th YES entry rejected before the trade engine fires."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("SAFE_CLOSE_DIRECTION_LIMIT_PER_HOUR", "3")
    bootstrap_default_strategies()

    now = datetime.now(timezone.utc).timestamp()
    for _ in range(3):
        ssj._safe_close_record_entry(str(_USER_UUID), "YES", now - 60.0)

    reached_engine = _run(row=_user_row(), cand=_late_entry_candidate("YES"))
    assert not reached_engine, (
        "User at the directional limit must be rejected at step 3d "
        "before reaching the trade engine."
    )


def test_gate_allows_when_user_under_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """User with fewer prior entries than the limit MUST proceed."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("SAFE_CLOSE_DIRECTION_LIMIT_PER_HOUR", "3")
    bootstrap_default_strategies()

    now = datetime.now(timezone.utc).timestamp()
    for _ in range(2):
        ssj._safe_close_record_entry(str(_USER_UUID), "YES", now - 60.0)

    reached_engine = _run(row=_user_row(), cand=_late_entry_candidate("YES"))
    assert reached_engine, "User under limit must reach engine."


def test_gate_isolates_sides(monkeypatch: pytest.MonkeyPatch) -> None:
    """A user at the YES limit must still be allowed to enter NO —
    the gate is per-side."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("SAFE_CLOSE_DIRECTION_LIMIT_PER_HOUR", "3")
    bootstrap_default_strategies()

    now = datetime.now(timezone.utc).timestamp()
    for _ in range(5):  # well over limit
        ssj._safe_close_record_entry(str(_USER_UUID), "YES", now - 60.0)

    reached_engine = _run(row=_user_row(), cand=_late_entry_candidate("NO"))
    assert reached_engine, (
        "Per-side isolation: YES limit reached must not block NO entries."
    )


def test_gate_no_op_for_non_safe_close_presets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Even with a full YES window, a close_sweep / flip_hunter user
    must bypass the gate — it's scoped to safe_close only."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("SAFE_CLOSE_DIRECTION_LIMIT_PER_HOUR", "3")
    bootstrap_default_strategies()

    now = datetime.now(timezone.utc).timestamp()
    for _ in range(10):
        ssj._safe_close_record_entry(str(_USER_UUID), "YES", now - 60.0)

    for preset in ("close_sweep", "flip_hunter"):
        reached_engine = _run(
            row=_user_row(active_preset=preset),
            cand=_late_entry_candidate("YES"),
        )
        assert reached_engine, (
            f"Gate must be scoped to safe_close; {preset} candidate "
            f"was incorrectly blocked."
        )


def test_disabled_gate_passes_at_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """SAFE_CLOSE_DIRECTION_LIMIT_PER_HOUR=0 disables the gate; even a
    user with 50 prior entries must reach engine."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("SAFE_CLOSE_DIRECTION_LIMIT_PER_HOUR", "0")
    bootstrap_default_strategies()

    now = datetime.now(timezone.utc).timestamp()
    for _ in range(50):
        ssj._safe_close_record_entry(str(_USER_UUID), "YES", now - 60.0)

    reached_engine = _run(row=_user_row(), cand=_late_entry_candidate("YES"))
    assert reached_engine, (
        "Disable sentinel broken: limit=0 must skip the gate."
    )


def test_record_on_accepted_entry_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Accepted safe_close entries must be recorded; the count must
    advance from 0 to 1 after one successful execution. (Duplicate /
    rejected entries are not recorded — verified by the test below.)"""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("SAFE_CLOSE_DIRECTION_LIMIT_PER_HOUR", "10")
    bootstrap_default_strategies()

    now = datetime.now(timezone.utc).timestamp()
    assert ssj._safe_close_recent_count(str(_USER_UUID), "YES", now) == 0

    reached_engine = _run(row=_user_row(), cand=_late_entry_candidate("YES"))
    assert reached_engine, "Sanity: gate should allow this fresh entry."

    # The accept path must have logged the entry.
    assert ssj._safe_close_recent_count(str(_USER_UUID), "YES", now) == 1


def test_no_record_on_insert_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    """When `_insert_execution_queue` returns False (concurrent tick
    won the ON CONFLICT race), the OTHER tick is authoritative — this
    tick must NOT record again or the user gets double-counted toward
    the cap and is wrongly blocked sooner than intended."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("SAFE_CLOSE_DIRECTION_LIMIT_PER_HOUR", "10")
    bootstrap_default_strategies()

    reached_engine = _run(
        row=_user_row(),
        cand=_late_entry_candidate("YES"),
        insert_returns=False,
    )
    assert reached_engine, "engine.execute should have run"
    now = datetime.now(timezone.utc).timestamp()
    assert ssj._safe_close_recent_count(str(_USER_UUID), "YES", now) == 0, (
        "inserted=False (concurrent ON CONFLICT) must not advance the "
        "counter — the other tick is authoritative for this trade."
    )


def test_no_record_on_duplicate_result(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the engine returns mode='duplicate', the entry never
    reaches the broker — directional exposure unchanged → no count."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("SAFE_CLOSE_DIRECTION_LIMIT_PER_HOUR", "10")
    bootstrap_default_strategies()

    async def _dup_execute(signal):
        return TradeResult(
            approved=True,
            mode="duplicate",
            order_id=uuid4(),
            position_id=uuid4(),
            rejection_reason=None,
            failed_gate_step=None,
            chosen_mode="paper",
            final_size_usdc=Decimal("10"),
        )

    _run(row=_user_row(), cand=_late_entry_candidate("YES"), execute=_dup_execute)
    now = datetime.now(timezone.utc).timestamp()
    assert ssj._safe_close_recent_count(str(_USER_UUID), "YES", now) == 0, (
        "Duplicate results must not advance the directional counter; "
        "the trade never reached the broker."
    )
