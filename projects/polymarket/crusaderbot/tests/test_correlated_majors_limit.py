"""Correlated crypto-majors same-direction entry guard
(WARP/correlated-majors-entry-guard).

Rationale: BTC/ETH/SOL move together intraday, so late_entry_v3 — which scores
each candle market independently — opens three same-direction positions on what
is effectively ONE directional bet when the majors all favour the same side at a
candle close. A single adverse move then stops out the whole cluster at once
(observed prod: a user with BTC+ETH+SOL all "yes" on one candle taking three
simultaneous sl_hit). The per-user max_concurrent count cap (5/12/20) does NOT
catch this — three correlated entries are well under the count limit. This gate
caps same-direction crypto-majors entries within one short same-candle window
at ``CORRELATED_MAJORS_SAME_DIR_LIMIT`` per (user, side).

Scope discipline:
  - Fires for ALL candle presets (correlation is a market property, not a preset
    one) — unlike the safe_close direction limiter, which is preset-scoped.
  - Only fires for cluster majors (BTC/ETH/SOL via metadata["cell"]); a
    non-cluster asset bypasses the gate entirely.
  - Per (user, side): opposite sides partially hedge and are counted separately;
    different users are independent.

Escape hatch: ``CORRELATED_MAJORS_SAME_DIR_LIMIT=0`` disables (runtime branches
on `> 0`). Negative values rejected at config load.

Gate / record lives in:
  ``services.signal_scan.signal_scan_job._process_candidate`` step 3d-ii.
Window state + helpers live in:
  ``services.signal_scan.signal_scan_job`` module level.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
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
    """Reset the StrategyRegistry and the in-process correlated-majors window
    between tests — leftover entries from one test would skew the next."""
    StrategyRegistry._reset_for_tests()
    ssj._correlated_majors_reset_for_tests()
    crusaderbot_config.get_settings.cache_clear()
    yield
    StrategyRegistry._reset_for_tests()
    ssj._correlated_majors_reset_for_tests()
    crusaderbot_config.get_settings.cache_clear()


# ---------------------------------------------------------------------
# Window helper — count / record / prune semantics.
# ---------------------------------------------------------------------


def test_recent_count_empty_returns_zero():
    now = datetime.now(timezone.utc).timestamp()
    assert ssj._correlated_majors_recent_count("user-A", "YES", now) == 0
    assert ssj._correlated_majors_recent_count("user-A", "NO", now) == 0


def test_record_then_count_increments():
    """A recorded entry shows up for the same (user, side) and only that key —
    the window aggregates ACROSS assets (the whole cluster), so the key is
    intentionally (user, side), never (user, side, asset)."""
    now = datetime.now(timezone.utc).timestamp()
    ssj._correlated_majors_record_entry("user-A", "YES", now)
    assert ssj._correlated_majors_recent_count("user-A", "YES", now) == 1
    assert ssj._correlated_majors_recent_count("user-A", "NO", now) == 0
    assert ssj._correlated_majors_recent_count("user-B", "YES", now) == 0


def test_side_normalization_is_case_insensitive():
    now = datetime.now(timezone.utc).timestamp()
    ssj._correlated_majors_record_entry("user-A", "yes", now)
    assert ssj._correlated_majors_recent_count("user-A", "YES", now) == 1
    assert ssj._correlated_majors_recent_count("user-A", "yes", now) == 1


def test_window_prunes_entries_older_than_window():
    """Entries older than the short same-candle window are evicted on read so a
    prior candle's burst never bleeds into the next."""
    now = datetime.now(timezone.utc).timestamp()
    w = ssj._CORRELATED_MAJORS_WINDOW_SEC
    # Two stale (2x window ago) + two recent (within window).
    for t in [now - 2 * w, now - 2 * w, now - w / 2, now - w / 2]:
        ssj._correlated_majors_record_entry("user-A", "YES", t)
    assert ssj._correlated_majors_recent_count("user-A", "YES", now) == 2


def test_window_boundary_exactly_at_cutoff_kept():
    """Entry exactly at the cutoff boundary must NOT be evicted (prune uses
    `>= cutoff`)."""
    now = datetime.now(timezone.utc).timestamp()
    ssj._correlated_majors_record_entry(
        "user-A", "YES", now - ssj._CORRELATED_MAJORS_WINDOW_SEC
    )
    assert ssj._correlated_majors_recent_count("user-A", "YES", now) == 1


def test_empty_keys_removed_after_full_prune():
    now = datetime.now(timezone.utc).timestamp()
    old = now - 2 * ssj._CORRELATED_MAJORS_WINDOW_SEC
    ssj._correlated_majors_record_entry("user-A", "YES", old)
    ssj._correlated_majors_record_entry("user-A", "YES", old)
    assert ("user-A", "YES") in ssj._correlated_majors_log
    assert ssj._correlated_majors_recent_count("user-A", "YES", now) == 0
    assert ("user-A", "YES") not in ssj._correlated_majors_log


def test_recent_count_does_not_create_empty_key():
    now = datetime.now(timezone.utc).timestamp()
    assert ssj._correlated_majors_recent_count("user-NEW", "YES", now) == 0
    assert ("user-NEW", "YES") not in ssj._correlated_majors_log


# ---------------------------------------------------------------------
# Asset resolver — only cluster majors are subject to the guard.
# ---------------------------------------------------------------------


def _cand_with_cell(cell, side: str = "YES") -> SignalCandidate:
    md = {
        "market_id": "market-001",
        "entry_price": 0.65,
        "fav_price_min": 0.60,
        "fav_price_max": 0.70,
        "underdog_mode": False,
    }
    if cell is not None:
        md["cell"] = cell
    return SignalCandidate(
        market_id="market-001",
        condition_id="market-001",
        side=side,
        confidence=0.7,
        suggested_size_usdc=10.0,
        strategy_name="late_entry_v3",
        signal_ts=datetime.now(timezone.utc),
        metadata=md,
    )


def test_asset_resolver_recognises_cluster_majors():
    assert ssj._major_asset_from_candidate(_cand_with_cell("BTC/5m")) == "BTC"
    assert ssj._major_asset_from_candidate(_cand_with_cell("eth/15m")) == "ETH"
    assert ssj._major_asset_from_candidate(_cand_with_cell("SOL/5m")) == "SOL"


def test_asset_resolver_returns_none_for_non_majors_and_missing():
    assert ssj._major_asset_from_candidate(_cand_with_cell("DOGE/5m")) is None
    assert ssj._major_asset_from_candidate(_cand_with_cell(None)) is None
    assert ssj._major_asset_from_candidate(_cand_with_cell("")) is None
    assert ssj._major_asset_from_candidate(_cand_with_cell(12345)) is None


# ---------------------------------------------------------------------
# Config knob — default + env override + negative rejection.
# ---------------------------------------------------------------------


def test_default_limit_is_1(monkeypatch: pytest.MonkeyPatch) -> None:
    # Owner directive 2026-06-10: BTC/ETH/SOL are one correlated bet — default
    # cap of 1 means only the best same-direction major trades per candle.
    _set_required_env(monkeypatch)
    monkeypatch.delenv("CORRELATED_MAJORS_SAME_DIR_LIMIT", raising=False)
    s = crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert s.CORRELATED_MAJORS_SAME_DIR_LIMIT == 1


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("CORRELATED_MAJORS_SAME_DIR_LIMIT", "1")
    s = crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert s.CORRELATED_MAJORS_SAME_DIR_LIMIT == 1


def test_disable_sentinel_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("CORRELATED_MAJORS_SAME_DIR_LIMIT", "0")
    s = crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert s.CORRELATED_MAJORS_SAME_DIR_LIMIT == 0


def test_negative_rejected_at_load(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("CORRELATED_MAJORS_SAME_DIR_LIMIT", "-1")
    with pytest.raises(ValidationError) as excinfo:
        crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert "CORRELATED_MAJORS_SAME_DIR_LIMIT" in str(excinfo.value)


# ---------------------------------------------------------------------
# Behavioural — gate in _process_candidate.
# ---------------------------------------------------------------------


_USER_UUID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


def _user_row(*, active_preset: str = "candle_auto") -> dict:
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
        "slug": "btc-updown-5m-test",
        "question": "Bitcoin Up or Down?",
        "status": "active",
        "yes_price": 0.55,
        "no_price": 0.45,
        "yes_token_id": "tok_yes",
        "no_token_id": "tok_no",
        "liquidity_usdc": 20000.0,
    }


def _major_candidate(asset: str = "BTC", side: str = "YES") -> SignalCandidate:
    return _cand_with_cell(f"{asset}/5m", side=side)


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
    open_majors: int = 0,
) -> bool:
    """Drive `_process_candidate` with the full mock stack and return True iff
    `_engine.execute` was reached (the gate did not short-circuit).

    ``open_majors`` stubs the DB-authoritative count of currently-open
    same-direction crypto-major positions (``_open_correlated_majors_count``) so
    a test can simulate prior open exposure WITHOUT the in-memory window — i.e.
    the post-restart / multi-worker case the window alone could not enforce."""
    engine_called = {"called": False}

    async def _track_execute(signal):
        engine_called["called"] = True
        return _approved_result()

    exec_fn = execute or _track_execute
    with patch.object(ssj, "_load_stale_queued_row", return_value=None), \
            patch.object(ssj, "_publication_already_queued", return_value=False), \
            patch.object(ssj, "_has_open_position_for_market", return_value=False), \
            patch.object(ssj, "_open_correlated_majors_count",
                         new=AsyncMock(return_value=open_majors)), \
            patch.object(ssj, "_load_market", return_value=_market_row()), \
            patch.object(ssj, "get_live_market_price",
                         new=AsyncMock(return_value=0.66)), \
            patch.object(ssj._engine, "execute", side_effect=exec_fn), \
            patch.object(ssj, "_insert_execution_queue", return_value=insert_returns), \
            patch.object(ssj, "_mark_executed", new=AsyncMock()):
        asyncio.run(ssj._process_candidate(row, cand))
    return engine_called["called"]


def test_gate_blocks_third_same_direction_major(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the default cap of 2, a user already holding 2 same-direction
    majors this candle MUST have the 3rd rejected before the trade engine."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("CORRELATED_MAJORS_SAME_DIR_LIMIT", "2")
    bootstrap_default_strategies()

    now = datetime.now(timezone.utc).timestamp()
    for _ in range(2):  # BTC + ETH already in, same side
        ssj._correlated_majors_record_entry(str(_USER_UUID), "YES", now - 5.0)

    reached_engine = _run(row=_user_row(), cand=_major_candidate("SOL", "YES"))
    assert not reached_engine, (
        "Third same-direction major must be rejected at step 3d-ii before "
        "reaching the trade engine."
    )


def test_gate_allows_when_under_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """With 1 prior same-direction major and cap 2, the 2nd MUST proceed."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("CORRELATED_MAJORS_SAME_DIR_LIMIT", "2")
    bootstrap_default_strategies()

    now = datetime.now(timezone.utc).timestamp()
    ssj._correlated_majors_record_entry(str(_USER_UUID), "YES", now - 5.0)

    reached_engine = _run(row=_user_row(), cand=_major_candidate("ETH", "YES"))
    assert reached_engine, "Second same-direction major (under cap) must reach engine."


def test_gate_isolates_opposite_sides(monkeypatch: pytest.MonkeyPatch) -> None:
    """A user at the YES cap must still enter a NO major — opposite directions
    partially hedge and are counted separately."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("CORRELATED_MAJORS_SAME_DIR_LIMIT", "2")
    bootstrap_default_strategies()

    now = datetime.now(timezone.utc).timestamp()
    for _ in range(3):  # well over the YES cap
        ssj._correlated_majors_record_entry(str(_USER_UUID), "YES", now - 5.0)

    reached_engine = _run(row=_user_row(), cand=_major_candidate("SOL", "NO"))
    assert reached_engine, "Per-side isolation: YES cap must not block a NO major."


def test_gate_no_op_for_non_major_asset(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-cluster asset (e.g. DOGE) bypasses the guard even when the user's
    same-direction window is full of majors."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("CORRELATED_MAJORS_SAME_DIR_LIMIT", "2")
    bootstrap_default_strategies()

    now = datetime.now(timezone.utc).timestamp()
    for _ in range(5):
        ssj._correlated_majors_record_entry(str(_USER_UUID), "YES", now - 5.0)

    reached_engine = _run(row=_user_row(), cand=_cand_with_cell("DOGE/5m", "YES"))
    assert reached_engine, "Non-cluster asset must bypass the correlation guard."


def test_gate_applies_across_all_candle_presets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unlike the safe_close limiter, the correlation guard is preset-agnostic:
    close_sweep / flip_hunter / candle_auto are all capped."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("CORRELATED_MAJORS_SAME_DIR_LIMIT", "2")
    bootstrap_default_strategies()

    for preset in ("candle_auto", "close_sweep", "flip_hunter", "safe_close"):
        ssj._correlated_majors_reset_for_tests()
        now = datetime.now(timezone.utc).timestamp()
        for _ in range(2):
            ssj._correlated_majors_record_entry(str(_USER_UUID), "YES", now - 5.0)
        reached_engine = _run(
            row=_user_row(active_preset=preset),
            cand=_major_candidate("SOL", "YES"),
        )
        assert not reached_engine, (
            f"Correlation guard must apply to {preset}; the 3rd same-direction "
            f"major was not blocked."
        )


def test_disabled_gate_passes_over_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """CORRELATED_MAJORS_SAME_DIR_LIMIT=0 disables the gate; a user with many
    prior majors must still reach engine."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("CORRELATED_MAJORS_SAME_DIR_LIMIT", "0")
    bootstrap_default_strategies()

    now = datetime.now(timezone.utc).timestamp()
    for _ in range(10):
        ssj._correlated_majors_record_entry(str(_USER_UUID), "YES", now - 5.0)

    reached_engine = _run(row=_user_row(), cand=_major_candidate("SOL", "YES"))
    assert reached_engine, "Disable sentinel broken: limit=0 must skip the gate."


def test_record_on_accepted_major_entry_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """An accepted major entry advances the cluster counter from 0 to 1."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("CORRELATED_MAJORS_SAME_DIR_LIMIT", "5")
    bootstrap_default_strategies()

    now = datetime.now(timezone.utc).timestamp()
    assert ssj._correlated_majors_recent_count(str(_USER_UUID), "YES", now) == 0

    reached_engine = _run(row=_user_row(), cand=_major_candidate("BTC", "YES"))
    assert reached_engine, "Sanity: fresh major entry should be allowed."
    assert ssj._correlated_majors_recent_count(str(_USER_UUID), "YES", now) == 1


def test_no_record_for_accepted_non_major(monkeypatch: pytest.MonkeyPatch) -> None:
    """An accepted NON-cluster entry must NOT advance the cluster counter."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("CORRELATED_MAJORS_SAME_DIR_LIMIT", "5")
    bootstrap_default_strategies()

    reached_engine = _run(row=_user_row(), cand=_cand_with_cell("DOGE/5m", "YES"))
    assert reached_engine, "Sanity: non-major should reach engine."
    now = datetime.now(timezone.utc).timestamp()
    assert ssj._correlated_majors_recent_count(str(_USER_UUID), "YES", now) == 0, (
        "Non-cluster assets must not contribute to the correlated-majors window."
    )


def test_no_record_on_insert_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    """When `_insert_execution_queue` returns False (concurrent tick won the ON
    CONFLICT race), this tick must NOT record — the other tick is authoritative,
    else the user is double-counted and blocked sooner than intended."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("CORRELATED_MAJORS_SAME_DIR_LIMIT", "5")
    bootstrap_default_strategies()

    reached_engine = _run(
        row=_user_row(), cand=_major_candidate("BTC", "YES"),
        insert_returns=False,
    )
    assert reached_engine, "engine.execute should have run"
    now = datetime.now(timezone.utc).timestamp()
    assert ssj._correlated_majors_recent_count(str(_USER_UUID), "YES", now) == 0, (
        "inserted=False (concurrent ON CONFLICT) must not advance the counter."
    )


def test_no_record_on_duplicate_result(monkeypatch: pytest.MonkeyPatch) -> None:
    """A mode='duplicate' result never reaches the broker → no count."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("CORRELATED_MAJORS_SAME_DIR_LIMIT", "5")
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

    _run(row=_user_row(), cand=_major_candidate("BTC", "YES"), execute=_dup_execute)
    now = datetime.now(timezone.utc).timestamp()
    assert ssj._correlated_majors_recent_count(str(_USER_UUID), "YES", now) == 0, (
        "Duplicate results must not advance the correlated-majors counter."
    )


def test_full_cluster_sequence_caps_at_two(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end: BTC then ETH then SOL, all same side, in one window. The first
    two reach the engine and record; the third is blocked — exactly the prod
    pattern this guard fixes (three simultaneous correlated sl_hit → now two)."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("CORRELATED_MAJORS_SAME_DIR_LIMIT", "2")
    bootstrap_default_strategies()

    assert _run(row=_user_row(), cand=_major_candidate("BTC", "YES")) is True
    assert _run(row=_user_row(), cand=_major_candidate("ETH", "YES")) is True
    assert _run(row=_user_row(), cand=_major_candidate("SOL", "YES")) is False

    now = datetime.now(timezone.utc).timestamp()
    assert ssj._correlated_majors_recent_count(str(_USER_UUID), "YES", now) == 2


# ---------------------------------------------------------------------
# DB-authoritative count (survives restart / multiple workers).
# The in-memory window alone reset to empty on a Fly redeploy mid-candle,
# letting a 3rd correlated major open — the observed prod defect.
# ---------------------------------------------------------------------


def test_default_cap_one_blocks_second_same_direction_major(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default cap 1: a fresh BTC YES is allowed, but a same-direction ETH YES
    is blocked — BTC/ETH/SOL count as one correlated bet."""
    _set_required_env(monkeypatch)
    monkeypatch.delenv("CORRELATED_MAJORS_SAME_DIR_LIMIT", raising=False)
    bootstrap_default_strategies()

    assert _run(row=_user_row(), cand=_major_candidate("BTC", "YES")) is True
    assert _run(row=_user_row(), cand=_major_candidate("ETH", "YES")) is False


def test_db_open_count_blocks_with_empty_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE restart-robustness guarantee. The in-memory window is empty (as it is
    immediately after a Fly redeploy), but the DB reports one already-open
    same-direction major. With the default cap of 1 the next major MUST still be
    blocked — proving the cap no longer depends on volatile in-memory state."""
    _set_required_env(monkeypatch)
    monkeypatch.delenv("CORRELATED_MAJORS_SAME_DIR_LIMIT", raising=False)
    bootstrap_default_strategies()

    now = datetime.now(timezone.utc).timestamp()
    assert ssj._correlated_majors_recent_count(str(_USER_UUID), "YES", now) == 0

    reached_engine = _run(
        row=_user_row(), cand=_major_candidate("SOL", "YES"), open_majors=1,
    )
    assert not reached_engine, (
        "An open same-direction major in the DB must enforce the cap even when "
        "the in-memory window was wiped by a restart."
    )


def test_db_open_count_caps_at_two_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With cap 2 and the window empty, the DB count is the sole source: one open
    major still passes (1 < 2); two open majors blocks the third (2 >= 2)."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("CORRELATED_MAJORS_SAME_DIR_LIMIT", "2")
    bootstrap_default_strategies()

    assert _run(
        row=_user_row(), cand=_major_candidate("ETH", "YES"), open_majors=1,
    ) is True
    assert _run(
        row=_user_row(), cand=_major_candidate("SOL", "YES"), open_majors=2,
    ) is False


def test_db_open_count_isolates_opposite_side(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The DB count is queried per-side: an open YES major does not block a NO
    major (opposite directions partially hedge)."""
    _set_required_env(monkeypatch)
    monkeypatch.delenv("CORRELATED_MAJORS_SAME_DIR_LIMIT", raising=False)
    bootstrap_default_strategies()

    # _open_correlated_majors_count is stubbed per-run; here the NO candidate is
    # told there are 0 open NO majors even though (conceptually) a YES is open.
    reached_engine = _run(
        row=_user_row(), cand=_major_candidate("SOL", "NO"), open_majors=0,
    )
    assert reached_engine, "Opposite-side major must not be blocked by the cap."


def test_gate_effective_count_is_max_of_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pure-gate unit: the effective count is max(window, open_position_count).
    Window 0 + DB 1 with cap 1 => block; window 1 + DB 0 with cap 1 => block."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("CORRELATED_MAJORS_SAME_DIR_LIMIT", "1")
    crusaderbot_config.get_settings.cache_clear()

    import logging
    log = logging.getLogger("test")

    # DB source alone trips the cap (window empty).
    assert ssj._gate_correlated_majors(
        user_id=_USER_UUID, side="YES", market_id="m", asset="BTC",
        open_position_count=1, log=log,
    ) == "skipped_correlated_majors_concentration"

    # Window source alone trips the cap (DB 0).
    now = datetime.now(timezone.utc).timestamp()
    ssj._correlated_majors_record_entry(str(_USER_UUID), "YES", now)
    assert ssj._gate_correlated_majors(
        user_id=_USER_UUID, side="YES", market_id="m", asset="ETH",
        open_position_count=0, log=log,
    ) == "skipped_correlated_majors_concentration"
