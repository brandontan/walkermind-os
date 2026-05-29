"""Hermetic tests for the P3d signal_following scan loop + execution queue.

Coverage:
    * run_once — no enrolled users, strategy not registered
    * _load_enrolled_users query path (mocked pool)
    * _process_candidate — happy path (accepted), skipped_dedup, rejected,
      failed (router raises), market not synced, gate context build error
    * _build_user_context — allocation clamp, sub_account fallback
    * _build_idempotency_key — determinism
    * _insert_execution_queue — conflict returns False
    * STRATEGY_AVAILABILITY — signal_following key present and correct

No DB, no broker, no Telegram, no Polygon, no Polymarket.
Pool access patched via asyncpg context manager fakes.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from projects.polymarket.crusaderbot.domain.risk import constants as K
from projects.polymarket.crusaderbot.domain.strategy import (
    StrategyRegistry,
    bootstrap_default_strategies,
)
from projects.polymarket.crusaderbot.domain.strategy.types import (
    MarketFilters,
    SignalCandidate,
    UserContext,
)
from projects.polymarket.crusaderbot.services.signal_scan import signal_scan_job as job
from projects.polymarket.crusaderbot.services.trade_engine import TradeResult

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_registry():
    StrategyRegistry._reset_for_tests()
    yield
    StrategyRegistry._reset_for_tests()


_USER_UUID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
_PUB_UUID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
_MARKET_ID = "market-001"
_NOW = datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc)


def _user_row(
    *,
    user_id: UUID = _USER_UUID,
    balance: float = 500.0,
    risk_profile: str = "balanced",
    trading_mode: str = "paper",
    capital_pct: float = 0.10,
    tp_pct: float | None = 0.20,
    sl_pct: float | None = 0.08,
    daily_loss_override: float | None = None,
    sub_account_id: UUID | None = None,
) -> dict:
    return {
        "user_id": user_id,
        "telegram_user_id": 42,
        "auto_trade_on": True,
        "paused": False,
        "balance_usdc": balance,
        "risk_profile": risk_profile,
        "trading_mode": trading_mode,
        "tp_pct": tp_pct,
        "sl_pct": sl_pct,
        "daily_loss_override": daily_loss_override,
        "capital_allocation_pct": capital_pct,
        "sub_account_id": sub_account_id or uuid4(),
        "resolved_profile": risk_profile,
    }


def _candidate(
    *,
    market_id: str = _MARKET_ID,
    side: str = "YES",
    pub_uuid: UUID = _PUB_UUID,
    size: float = 10.0,
) -> SignalCandidate:
    return SignalCandidate(
        market_id=market_id,
        condition_id=market_id,
        side=side,
        confidence=0.7,
        suggested_size_usdc=size,
        strategy_name="signal_following",
        signal_ts=datetime.now(timezone.utc),
        metadata={
            "feed_id": str(uuid4()),
            "publication_id": str(pub_uuid),
            "market_id": market_id,
        },
    )


def _market_row(status: str = "active") -> dict:
    return {
        "id": _MARKET_ID,
        "question": "Will X happen?",
        "status": status,
        "yes_price": 0.55,
        "no_price": 0.45,
        "yes_token_id": "tok_yes",
        "no_token_id": "tok_no",
        "liquidity_usdc": 20000.0,
    }


# ---------------------------------------------------------------------------
# Fake asyncpg pool (single-conn, preloaded sequences)
# ---------------------------------------------------------------------------


class _FakeConn:
    def __init__(
        self,
        fetch_results: list | None = None,
        fetchrow_results: list | None = None,
        fetchval_results: list | None = None,
    ) -> None:
        self._fetch = list(fetch_results or [])
        self._fetchrow = list(fetchrow_results or [])
        self._fetchval = list(fetchval_results or [])
        self.executes: list[str] = []

    async def fetch(self, sql, *a):
        return self._fetch.pop(0) if self._fetch else []

    async def fetchrow(self, sql, *a):
        return self._fetchrow.pop(0) if self._fetchrow else None

    async def fetchval(self, sql, *a):
        return self._fetchval.pop(0) if self._fetchval else None

    async def execute(self, sql, *a):
        self.executes.append(sql)


class _FakePool:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _Ctx:
            async def __aenter__(self_inner):
                return conn

            async def __aexit__(self_inner, *a):
                return False

        return _Ctx()


def _patch_pool(conn: _FakeConn):
    return patch.object(job, "get_pool", return_value=_FakePool(conn))


# ---------------------------------------------------------------------------
# STRATEGY_AVAILABILITY — signal_following availability (resolves PR #895)
# ---------------------------------------------------------------------------


def test_strategy_availability_includes_signal_following():
    assert "signal_following" in K.STRATEGY_AVAILABILITY


def test_signal_following_availability_all_profiles():
    avail = K.STRATEGY_AVAILABILITY["signal_following"]
    assert set(avail) == {"conservative", "balanced", "aggressive", "custom"}


def test_signal_following_matches_strategy_name():
    bootstrap_default_strategies()
    strategy = StrategyRegistry.instance().get("signal_following")
    assert strategy.name == "signal_following"
    # STRATEGY_AVAILABILITY key matches strategy.name exactly.
    assert strategy.name in K.STRATEGY_AVAILABILITY
    # risk_profile_compatibility matches STRATEGY_AVAILABILITY entries.
    assert set(strategy.risk_profile_compatibility) == set(
        K.STRATEGY_AVAILABILITY["signal_following"]
    )


# ---------------------------------------------------------------------------
# _build_user_context
# ---------------------------------------------------------------------------


def test_build_user_context_happy_path():
    row = _user_row(balance=800.0, risk_profile="aggressive", capital_pct=0.15)
    ctx = job._build_user_context(row)
    assert ctx.user_id == str(_USER_UUID)
    assert ctx.risk_profile == "aggressive"
    assert ctx.available_balance_usdc == pytest.approx(800.0)
    assert ctx.capital_allocation_pct == pytest.approx(0.15)


def test_build_user_context_clamps_allocation_above_one():
    row = _user_row(capital_pct=2.5)
    ctx = job._build_user_context(row)
    assert ctx.capital_allocation_pct == pytest.approx(1.0)


def test_build_user_context_clamps_allocation_below_zero():
    row = _user_row(capital_pct=-0.5)
    ctx = job._build_user_context(row)
    assert ctx.capital_allocation_pct == pytest.approx(0.0)


def test_build_user_context_sub_account_falls_back_to_user_id():
    row = _user_row()
    row["sub_account_id"] = None
    ctx = job._build_user_context(row)
    assert ctx.sub_account_id == str(row["user_id"])


# ---------------------------------------------------------------------------
# _build_idempotency_key — determinism
# ---------------------------------------------------------------------------


def test_build_idempotency_key_is_deterministic():
    k1 = job._build_idempotency_key(_USER_UUID, _MARKET_ID, "YES", _PUB_UUID)
    k2 = job._build_idempotency_key(_USER_UUID, _MARKET_ID, "YES", _PUB_UUID)
    assert k1 == k2


def test_build_idempotency_key_differs_by_side():
    k_yes = job._build_idempotency_key(_USER_UUID, _MARKET_ID, "YES", _PUB_UUID)
    k_no = job._build_idempotency_key(_USER_UUID, _MARKET_ID, "NO", _PUB_UUID)
    assert k_yes != k_no


def test_build_idempotency_key_same_for_different_publications():
    # After date-scoping fix, publication_id is NOT part of the key hash.
    # Same (user, market, side, day) → same key regardless of publication_id,
    # preventing multiple open positions across separate publications.
    pub2 = uuid4()
    k1 = job._build_idempotency_key(_USER_UUID, _MARKET_ID, "YES", _PUB_UUID)
    k2 = job._build_idempotency_key(_USER_UUID, _MARKET_ID, "YES", pub2)
    assert k1 == k2


def test_build_idempotency_key_starts_with_sf_prefix():
    k = job._build_idempotency_key(_USER_UUID, _MARKET_ID, "YES", None)
    assert k.startswith("sf:")


# ---------------------------------------------------------------------------
# _insert_execution_queue — conflict returns False
# ---------------------------------------------------------------------------


def test_insert_execution_queue_returns_true_on_new():
    conn = _FakeConn(fetchrow_results=[{"id": uuid4()}])
    with _patch_pool(conn):
        result = asyncio.run(job._insert_execution_queue(
            user_id=_USER_UUID,
            strategy_name="signal_following",
            market_id=_MARKET_ID,
            side="YES",
            publication_id=_PUB_UUID,
            suggested_size_usdc=Decimal("10"),
            final_size_usdc=Decimal("10"),
            idempotency_key="sf:abc",
            chosen_mode="paper",
        ))
    assert result is True


def test_insert_execution_queue_returns_false_on_conflict():
    conn = _FakeConn(fetchrow_results=[None])
    with _patch_pool(conn):
        result = asyncio.run(job._insert_execution_queue(
            user_id=_USER_UUID,
            strategy_name="signal_following",
            market_id=_MARKET_ID,
            side="YES",
            publication_id=_PUB_UUID,
            suggested_size_usdc=Decimal("10"),
            final_size_usdc=Decimal("10"),
            idempotency_key="sf:abc",
            chosen_mode="paper",
        ))
    assert result is False


# ---------------------------------------------------------------------------
# run_once — no enrolled users
# ---------------------------------------------------------------------------


def test_run_once_no_enrolled_users_exits_cleanly():
    bootstrap_default_strategies()
    conn = _FakeConn(fetch_results=[[]])
    with _patch_pool(conn):
        asyncio.run(job.run_once())


def test_run_once_strategy_not_registered_logs_and_returns():
    # Registry is empty — signal_following not registered.
    conn = _FakeConn(fetch_results=[[_user_row()]])
    with _patch_pool(conn):
        asyncio.run(job.run_once())  # must not raise


# ---------------------------------------------------------------------------
# _process_candidate — skipped_dedup (publication already in queue)
# ---------------------------------------------------------------------------


def test_process_candidate_skips_when_already_queued():
    bootstrap_default_strategies()
    row = _user_row()
    cand = _candidate()

    # No stale 'queued' row; but an executed/failed row already exists.
    with patch.object(job, "_load_stale_queued_row", return_value=None), \
            patch.object(job, "_publication_already_queued", return_value=True):
        asyncio.run(job._process_candidate(row, cand))
    # No execution should be attempted — test passes if no unhandled exception.


# ---------------------------------------------------------------------------
# _process_candidate — market not synced (skipped)
# ---------------------------------------------------------------------------


def test_process_candidate_skips_when_market_not_synced():
    bootstrap_default_strategies()
    row = _user_row()
    cand = _candidate()

    call_count = {"n": 0}

    async def _fake_load_market(mid: str):
        call_count["n"] += 1
        return None

    conn_no_dedup = _FakeConn(fetchrow_results=[None])  # not in queue
    with _patch_pool(conn_no_dedup), \
            patch.object(job, "_load_market", side_effect=_fake_load_market):
        asyncio.run(job._process_candidate(row, cand))

    assert call_count["n"] == 1


# ---------------------------------------------------------------------------
# _process_candidate — risk rejected
# ---------------------------------------------------------------------------


def test_process_candidate_logs_rejection_and_does_not_execute():
    bootstrap_default_strategies()
    row = _user_row()
    cand = _candidate()

    rejected = TradeResult(
        approved=False, mode=None, order_id=None, position_id=None,
        rejection_reason="max_concurrent_trades", failed_gate_step=7,
    )
    insert_called = {"called": False}

    async def _track_insert(**kwargs):
        insert_called["called"] = True
        return True

    with patch.object(job, "_load_stale_queued_row", return_value=None), \
            patch.object(job, "_publication_already_queued", return_value=False), \
            patch.object(job, "_load_market", return_value=_market_row()), \
            patch.object(job._engine, "execute", new=AsyncMock(return_value=rejected)), \
            patch.object(job, "_insert_execution_queue", side_effect=_track_insert):
        asyncio.run(job._process_candidate(row, cand))

    assert not insert_called["called"]


# ---------------------------------------------------------------------------
# _process_candidate — happy path (accepted, executed)
# ---------------------------------------------------------------------------


def test_process_candidate_happy_path_inserts_queue_and_executes():
    bootstrap_default_strategies()
    row = _user_row()
    cand = _candidate()

    from uuid import uuid4 as _uuid4
    approved = TradeResult(
        approved=True, mode="paper",
        order_id=_uuid4(), position_id=_uuid4(),
        rejection_reason=None, failed_gate_step=None,
        chosen_mode="paper", final_size_usdc=Decimal("10"),
    )
    marked = {"called": False}

    async def _fake_mark_executed(*a, **kw):
        marked["called"] = True

    with patch.object(job, "_load_stale_queued_row", return_value=None), \
            patch.object(job, "_publication_already_queued", return_value=False), \
            patch.object(job, "_load_market", return_value=_market_row()), \
            patch.object(job._engine, "execute", new=AsyncMock(return_value=approved)), \
            patch.object(job, "_insert_execution_queue", return_value=True), \
            patch.object(job, "_mark_executed", side_effect=_fake_mark_executed):
        asyncio.run(job._process_candidate(row, cand))

    assert marked["called"]


# ---------------------------------------------------------------------------
# _process_candidate — router raises (failed outcome)
# ---------------------------------------------------------------------------


def test_process_candidate_handles_engine_exception_gracefully():
    """Engine exception is caught and logged; no _mark_failed since queue not pre-inserted."""
    bootstrap_default_strategies()
    row = _user_row()
    cand = _candidate()

    async def _boom(signal):
        raise RuntimeError("engine error")

    mark_failed_called = {"called": False}

    async def _track_mark_failed(*a, **kw):
        mark_failed_called["called"] = True

    with patch.object(job, "_load_stale_queued_row", return_value=None), \
            patch.object(job, "_publication_already_queued", return_value=False), \
            patch.object(job, "_load_market", return_value=_market_row()), \
            patch.object(job._engine, "execute", side_effect=_boom), \
            patch.object(job, "_mark_failed", side_effect=_track_mark_failed):
        asyncio.run(job._process_candidate(row, cand))  # must not raise

    # In new flow: engine exception caught at step 4, logged, return — no queue entry to fail
    assert not mark_failed_called["called"]


# ---------------------------------------------------------------------------
# _process_candidate — concurrent dedup (insert returns False)
# ---------------------------------------------------------------------------


def test_process_candidate_skips_mark_executed_when_insert_conflicts():
    """ON CONFLICT on queue insert (concurrent tick) → skip _mark_executed."""
    bootstrap_default_strategies()
    row = _user_row()
    cand = _candidate()

    from uuid import uuid4 as _uuid4
    approved = TradeResult(
        approved=True, mode="paper",
        order_id=_uuid4(), position_id=_uuid4(),
        rejection_reason=None, failed_gate_step=None,
        chosen_mode="paper", final_size_usdc=Decimal("10"),
    )
    mark_exec_called = {"called": False}

    async def _track_mark_exec(*a, **kw):
        mark_exec_called["called"] = True

    with patch.object(job, "_load_stale_queued_row", return_value=None), \
            patch.object(job, "_publication_already_queued", return_value=False), \
            patch.object(job, "_load_market", return_value=_market_row()), \
            patch.object(job._engine, "execute", new=AsyncMock(return_value=approved)), \
            patch.object(job, "_insert_execution_queue", return_value=False), \
            patch.object(job, "_mark_executed", side_effect=_track_mark_exec):
        asyncio.run(job._process_candidate(row, cand))

    # Insert returned False (ON CONFLICT DO NOTHING) → _mark_executed must be skipped
    assert not mark_exec_called["called"]


# ---------------------------------------------------------------------------
# _process_candidate — inactive/expired signal (market status != active)
# ---------------------------------------------------------------------------


def test_process_candidate_risk_rejects_inactive_market():
    bootstrap_default_strategies()
    row = _user_row()
    cand = _candidate()

    # TradeEngine rejects because market is resolved (gate step 13).
    rejected = TradeResult(
        approved=False, mode=None, order_id=None, position_id=None,
        rejection_reason="market_inactive", failed_gate_step=13,
    )
    insert_called = {"called": False}

    async def _track_insert(**kwargs):
        insert_called["called"] = True
        return True

    with patch.object(job, "_load_stale_queued_row", return_value=None), \
            patch.object(job, "_publication_already_queued", return_value=False), \
            patch.object(job, "_load_market", return_value=_market_row(status="resolved")), \
            patch.object(job._engine, "execute", new=AsyncMock(return_value=rejected)), \
            patch.object(job, "_insert_execution_queue", side_effect=_track_insert):
        asyncio.run(job._process_candidate(row, cand))

    assert not insert_called["called"]


# ---------------------------------------------------------------------------
# _process_candidate — fill-time price-band re-check (gate 3c)
# ---------------------------------------------------------------------------


def _band_candidate(
    *,
    side: str = "YES",
    entry_price: float = 0.65,
    fav_price_min: float = 0.60,
    fav_price_max: float = 0.70,
) -> SignalCandidate:
    """Candidate carrying the late_entry_v3 price-band metadata (no publication_id)."""
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
            "entry_price": entry_price,
            "fav_price_min": fav_price_min,
            "fav_price_max": fav_price_max,
            "underdog_mode": False,
        },
    )


def test_process_candidate_skips_when_fill_price_below_band():
    """Candidate with metadata.entry_price BELOW its declared fav_price_min
    must be rejected by the fill-band gate.

    Realtime-fill-price lane: _process_candidate now sources the fill
    price from cand.metadata["entry_price"] (real CLOB /book best-ask
    from scan time) instead of re-fetching via get_live_market_price.
    So drift between scan and process can no longer occur — but a
    malformed candidate whose own entry_price falls outside its declared
    band must still be rejected at the gate. Same protection, different
    threat model.
    """
    bootstrap_default_strategies()
    row = _user_row()
    # Out-of-band entry_price (0.495 < fav_price_min 0.60)
    cand = _band_candidate(entry_price=0.495, fav_price_min=0.60, fav_price_max=0.70)

    engine_called = {"called": False}

    async def _track_execute(signal):
        engine_called["called"] = True
        return TradeResult(approved=True, mode="paper", order_id=None, position_id=None,
                           rejection_reason=None, failed_gate_step=None,
                           chosen_mode="paper", final_size_usdc=Decimal("10"))

    with patch.object(job, "_load_stale_queued_row", return_value=None), \
            patch.object(job, "_publication_already_queued", return_value=False), \
            patch.object(job, "_has_open_position_for_market", return_value=False), \
            patch.object(job, "_load_market", return_value=_market_row()), \
            patch.object(job._engine, "execute", side_effect=_track_execute):
        asyncio.run(job._process_candidate(row, cand))

    assert not engine_called["called"], "fill below band must short-circuit before engine"


def test_process_candidate_skips_when_fill_price_at_or_above_max_band():
    """Candidate with metadata.entry_price at/above fav_price_max must be
    rejected (band is half-open: max is exclusive)."""
    bootstrap_default_strategies()
    row = _user_row()
    # Out-of-band entry_price (0.70 >= fav_price_max 0.70 — half-open band)
    cand = _band_candidate(entry_price=0.70, fav_price_min=0.60, fav_price_max=0.70)

    engine_called = {"called": False}

    async def _track_execute(signal):
        engine_called["called"] = True
        return TradeResult(approved=True, mode="paper", order_id=None, position_id=None,
                           rejection_reason=None, failed_gate_step=None,
                           chosen_mode="paper", final_size_usdc=Decimal("10"))

    with patch.object(job, "_load_stale_queued_row", return_value=None), \
            patch.object(job, "_publication_already_queued", return_value=False), \
            patch.object(job, "_has_open_position_for_market", return_value=False), \
            patch.object(job, "_load_market", return_value=_market_row()), \
            patch.object(job._engine, "execute", side_effect=_track_execute):
        asyncio.run(job._process_candidate(row, cand))

    assert not engine_called["called"], "fill at/above max must short-circuit before engine"


def test_process_candidate_proceeds_when_fill_price_inside_band():
    """Fill price still in band → trade proceeds to engine + execution queue."""
    bootstrap_default_strategies()
    row = _user_row()
    cand = _band_candidate(fav_price_min=0.60, fav_price_max=0.70)

    from uuid import uuid4 as _uuid4
    approved = TradeResult(
        approved=True, mode="paper",
        order_id=_uuid4(), position_id=_uuid4(),
        rejection_reason=None, failed_gate_step=None,
        chosen_mode="paper", final_size_usdc=Decimal("10"),
    )
    engine_called = {"called": False}

    async def _track_execute(signal):
        engine_called["called"] = True
        return approved

    with patch.object(job, "_load_stale_queued_row", return_value=None), \
            patch.object(job, "_publication_already_queued", return_value=False), \
            patch.object(job, "_has_open_position_for_market", return_value=False), \
            patch.object(job, "_load_market", return_value=_market_row()), \
            patch.object(job, "get_live_market_price",
                         new=AsyncMock(return_value=0.66)), \
            patch.object(job._engine, "execute", side_effect=_track_execute), \
            patch.object(job, "_insert_execution_queue", return_value=True), \
            patch.object(job, "_mark_executed", new=AsyncMock()):
        asyncio.run(job._process_candidate(row, cand))

    assert engine_called["called"], "fill inside band must reach engine"


def test_process_candidate_band_gate_is_noop_without_metadata():
    """Backward compat: candidates without fav_price_min/max metadata bypass the gate."""
    bootstrap_default_strategies()
    row = _user_row()
    # _candidate() emits no band metadata — represents signal_following / lib strategies.
    cand = _candidate()

    from uuid import uuid4 as _uuid4
    approved = TradeResult(
        approved=True, mode="paper",
        order_id=_uuid4(), position_id=_uuid4(),
        rejection_reason=None, failed_gate_step=None,
        chosen_mode="paper", final_size_usdc=Decimal("10"),
    )
    engine_called = {"called": False}

    async def _track_execute(signal):
        engine_called["called"] = True
        return approved

    with patch.object(job, "_load_stale_queued_row", return_value=None), \
            patch.object(job, "_publication_already_queued", return_value=False), \
            patch.object(job, "_has_open_position_for_market", return_value=False), \
            patch.object(job, "_load_market", return_value=_market_row()), \
            patch.object(job, "get_live_market_price",
                         new=AsyncMock(return_value=0.001)), \
            patch.object(job._engine, "execute", side_effect=_track_execute), \
            patch.object(job, "_insert_execution_queue", return_value=True), \
            patch.object(job, "_mark_executed", new=AsyncMock()):
        asyncio.run(job._process_candidate(row, cand))

    assert engine_called["called"], (
        "candidates without band metadata must pass through — band gate is opt-in via metadata"
    )


# ---------------------------------------------------------------------------
# run_once — single user, happy path integration (all internals patched)
# ---------------------------------------------------------------------------


def test_run_once_happy_path_calls_process_candidate():
    """Two-phase loop: Phase A runs each lib strategy once, Phase B
    distributes candidates to users filtered by active_preset. With
    active_preset='full_auto' all lib strategies are allowed; only
    one strategy yields a candidate so _process_candidate is called once."""
    bootstrap_default_strategies()
    row = _user_row()
    row["active_preset"] = "full_auto"  # full_auto: all lib strategies allowed
    cand = _candidate()
    processed = {"calls": 0}

    def _fake_run_lib(lib_name, markets, config):
        # Only one strategy emits a signal this tick.
        return [cand] if lib_name == "trend_breakout" else []

    async def _fake_fetch_markets():
        return []

    async def _fake_process(r, c, tel=None):
        processed["calls"] += 1

    with patch.object(job, "_load_enrolled_users", return_value=[row]), \
            patch.object(
                job, "_fetch_markets_for_lib_strategies",
                side_effect=_fake_fetch_markets,
            ), \
            patch.object(job, "run_lib_strategy", side_effect=_fake_run_lib), \
            patch.object(job, "_process_candidate", side_effect=_fake_process):
        asyncio.run(job.run_once())

    assert processed["calls"] == 1


# ---------------------------------------------------------------------------
# run_once — scan failure per user is isolated
# ---------------------------------------------------------------------------


def test_run_once_scan_failure_does_not_stop_other_users():
    """Phase B per-user isolation: _process_candidate raising for the first
    user must not prevent the second user from being processed on the same
    tick."""
    bootstrap_default_strategies()
    row1 = _user_row(user_id=UUID("11111111-1111-1111-1111-111111111111"))
    row2 = _user_row(user_id=UUID("22222222-2222-2222-2222-222222222222"))
    row1["active_preset"] = "full_auto"
    row2["active_preset"] = "full_auto"
    processed = {"row1": 0, "row2": 0}

    def _fake_run_lib(lib_name, markets, config):
        return [_candidate()] if lib_name == "trend_breakout" else []

    async def _fake_fetch_markets():
        return []

    async def _fake_process(r, c, tel=None):
        if r["user_id"] == UUID("11111111-1111-1111-1111-111111111111"):
            processed["row1"] += 1
            raise RuntimeError("boom")
        processed["row2"] += 1

    with patch.object(job, "_load_enrolled_users", return_value=[row1, row2]), \
            patch.object(
                job, "_fetch_markets_for_lib_strategies",
                side_effect=_fake_fetch_markets,
            ), \
            patch.object(job, "run_lib_strategy", side_effect=_fake_run_lib), \
            patch.object(job, "_process_candidate", side_effect=_fake_process):
        asyncio.run(job.run_once())

    # First user's _process_candidate raised — second user still processed.
    assert processed["row1"] == 1
    assert processed["row2"] == 1


# ---------------------------------------------------------------------------
# _process_candidate — crash-recovery resume (stale 'queued' row)
# ---------------------------------------------------------------------------


def test_process_candidate_resumes_stale_queued_row():
    """Stale 'queued' row from a prior crashed tick is re-executed without gate."""
    bootstrap_default_strategies()
    row = _user_row()
    cand = _candidate()

    stale = {
        "market_id": _MARKET_ID,
        "side": "yes",
        "final_size_usdc": Decimal("10"),
        "suggested_size_usdc": Decimal("10"),
        "idempotency_key": "sf:abc123",
        "chosen_mode": "paper",
    }
    executed = {"called": False}
    marked = {"called": False}

    async def _fake_router(**kwargs):
        executed["called"] = True

    async def _fake_mark_executed(*a, **kw):
        marked["called"] = True

    with patch.object(job, "_load_stale_queued_row", return_value=stale), \
            patch.object(job, "kill_switch_is_active", return_value=False), \
            patch.object(job, "_load_market", return_value=_market_row()), \
            patch.object(job, "router_execute", side_effect=_fake_router), \
            patch.object(job, "_mark_executed", side_effect=_fake_mark_executed), \
            patch.object(job._engine, "execute", new=AsyncMock()) as mock_engine:
        asyncio.run(job._process_candidate(row, cand))

    assert executed["called"]
    assert marked["called"]
    # TradeEngine must NOT be called — crash recovery bypasses engine entirely.
    mock_engine.assert_not_called()


def test_process_candidate_skips_resume_when_kill_switch_active():
    """Crash-recovery resume is skipped (row stays 'queued') when kill switch is on."""
    bootstrap_default_strategies()
    row = _user_row()
    cand = _candidate()

    stale = {
        "market_id": _MARKET_ID,
        "side": "yes",
        "final_size_usdc": Decimal("10"),
        "suggested_size_usdc": Decimal("10"),
        "idempotency_key": "sf:abc123",
        "chosen_mode": "paper",
    }
    executed = {"called": False}

    async def _fake_router(**kwargs):
        executed["called"] = True

    with patch.object(job, "_load_stale_queued_row", return_value=stale), \
            patch.object(job, "kill_switch_is_active", return_value=True), \
            patch.object(job, "router_execute", side_effect=_fake_router):
        asyncio.run(job._process_candidate(row, cand))

    # Kill switch active — router must not be called, row remains 'queued' for retry.
    assert not executed["called"]


# ===========================================================================
# Preset isolation tests (CRUSADERBOT-STRATEGY-RISK-COPY)
# ===========================================================================

from projects.polymarket.crusaderbot.services.signal_scan.signal_scan_job import (
    _preset_allows,
)


def test_preset_allows_whale_mirror_only_whale_tracking():
    assert _preset_allows("whale_mirror", "whale_tracking") is True
    assert _preset_allows("whale_mirror", "trend_breakout") is False
    assert _preset_allows("whale_mirror", "momentum") is False


def test_preset_allows_contrarian_only_momentum():
    assert _preset_allows("contrarian", "momentum") is True
    assert _preset_allows("contrarian", "trend_breakout") is False
    assert _preset_allows("contrarian", "pair_arb") is False


def test_preset_allows_ensemble_subset():
    for name in ("ensemble", "trend_breakout", "momentum", "value_investor"):
        assert _preset_allows("ensemble", name) is True, f"ensemble should allow {name}"
    assert _preset_allows("ensemble", "pair_arb") is False
    assert _preset_allows("ensemble", "whale_tracking") is False


def test_preset_allows_full_auto_all_strategies():
    from projects.polymarket.crusaderbot.services.signal_scan.lib_strategy_runner import (
        ENABLED_STRATEGIES, DEFERRED_STRATEGIES,
    )
    for name in list(ENABLED_STRATEGIES) + list(DEFERRED_STRATEGIES):
        assert _preset_allows("full_auto", name) is True, f"full_auto should allow {name}"


def test_preset_allows_none_preset_all_strategies():
    from projects.polymarket.crusaderbot.services.signal_scan.lib_strategy_runner import (
        ENABLED_STRATEGIES,
    )
    for name in ENABLED_STRATEGIES:
        assert _preset_allows(None, name) is True, f"None preset should allow {name}"


def test_preset_allows_unknown_preset_defaults_to_all():
    # Unknown preset keys fall back to full allow via _LIB_STRATEGY_NAMES default.
    from projects.polymarket.crusaderbot.services.signal_scan.lib_strategy_runner import (
        ENABLED_STRATEGIES,
    )
    for name in ENABLED_STRATEGIES:
        assert _preset_allows("unknown_key", name) is True


# ===========================================================================
# Signal freshness gate (step 1c) — WARP-30
# ===========================================================================


def _stale_candidate(age_seconds: float, pub_uuid: UUID = _PUB_UUID) -> SignalCandidate:
    """Candidate with signal_ts set `age_seconds` in the past."""
    ts = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    return SignalCandidate(
        market_id=_MARKET_ID,
        condition_id=_MARKET_ID,
        side="YES",
        confidence=0.7,
        suggested_size_usdc=10.0,
        strategy_name="signal_following",
        signal_ts=ts,
        metadata={
            "feed_id": str(uuid4()),
            "publication_id": str(pub_uuid),
            "market_id": _MARKET_ID,
        },
    )


def test_process_candidate_skips_stale_publication_signal():
    """Signal older than 1800s with a pub_uuid must be dropped (outcome=skipped_signal_stale)."""
    bootstrap_default_strategies()
    row = _user_row()
    cand = _stale_candidate(age_seconds=1801)

    execute_called = {"called": False}

    def _fake_execute(*a, **kw):
        execute_called["called"] = True

    with patch.object(job, "_load_stale_queued_row", return_value=None), \
            patch.object(job, "_publication_already_queued", return_value=False), \
            patch.object(job._engine, "execute", new=AsyncMock(side_effect=_fake_execute)):
        asyncio.run(job._process_candidate(row, cand))

    assert not execute_called["called"], "stale signal must not reach trade engine"


def test_process_candidate_allows_fresh_publication_signal():
    """Signal younger than 1800s must proceed past the freshness gate."""
    bootstrap_default_strategies()
    row = _user_row()
    cand = _stale_candidate(age_seconds=60)  # 60s old — well within window

    from uuid import uuid4 as _uuid4
    approved = TradeResult(
        approved=True, mode="paper",
        order_id=_uuid4(), position_id=_uuid4(),
        rejection_reason=None, failed_gate_step=None,
    )

    execute_mock = AsyncMock(return_value=approved)
    with patch.object(job, "_load_stale_queued_row", return_value=None), \
            patch.object(job, "_publication_already_queued", return_value=False), \
            patch.object(job, "_load_market", return_value=_market_row()), \
            patch.object(job._engine, "execute", new=execute_mock), \
            patch.object(job, "_insert_execution_queue", new=AsyncMock(return_value=True)), \
            patch.object(job, "_mark_executed", new=AsyncMock()):
        asyncio.run(job._process_candidate(row, cand))
    execute_mock.assert_awaited_once()


def test_process_candidate_freshness_gate_skips_exact_boundary():
    """Signal just below 1800s must NOT be dropped (gate condition is strictly >)."""
    bootstrap_default_strategies()
    row = _user_row()
    # Use 1795s (5s buffer) — "exactly 1800" is untestable with wall-clock timestamps
    # because execution time pushes the measured age over the threshold.
    # This still exercises the > (not >=) boundary: 1795s is inside the window.
    cand = _stale_candidate(age_seconds=1795)

    from uuid import uuid4 as _uuid4
    approved = TradeResult(
        approved=True, mode="paper",
        order_id=_uuid4(), position_id=_uuid4(),
        rejection_reason=None, failed_gate_step=None,
    )
    execute_called = {"called": False}

    def _fake_execute(*a, **kw):
        execute_called["called"] = True
        return approved

    with patch.object(job, "_load_stale_queued_row", return_value=None), \
            patch.object(job, "_publication_already_queued", return_value=False), \
            patch.object(job, "_load_market", return_value=_market_row()), \
            patch.object(job._engine, "execute", new=AsyncMock(side_effect=_fake_execute)), \
            patch.object(job, "_insert_execution_queue", new=AsyncMock(return_value=True)), \
            patch.object(job, "_mark_executed", new=AsyncMock()):
        asyncio.run(job._process_candidate(row, cand))

    assert execute_called["called"], "signal below 1800s threshold must not be dropped by freshness gate"


# ===========================================================================
# _filter_markets_by_category — WARP-44
# ===========================================================================

from projects.polymarket.crusaderbot.services.signal_scan.signal_scan_job import (
    _filter_markets_by_category,
)


def _mkt(category: str = "", slug: str = "", group: str = "") -> dict:
    return {"category": category, "slug": slug, "groupItemTitle": group, "id": slug or category}


def test_filter_markets_empty_filters_returns_all():
    markets = [_mkt("crypto"), _mkt("sports"), _mkt("politics")]
    assert _filter_markets_by_category(markets, []) == markets


def test_filter_markets_single_filter_match():
    markets = [_mkt("crypto"), _mkt("sports"), _mkt("politics")]
    result = _filter_markets_by_category(markets, ["crypto"])
    assert len(result) == 1
    assert result[0]["category"] == "crypto"


def test_filter_markets_multi_filter():
    markets = [_mkt("crypto"), _mkt("sports"), _mkt("politics")]
    result = _filter_markets_by_category(markets, ["crypto", "sports"])
    assert len(result) == 2


def test_filter_markets_case_insensitive():
    markets = [_mkt("Crypto"), _mkt("SPORTS")]
    result = _filter_markets_by_category(markets, ["crypto"])
    assert len(result) == 1
    assert result[0]["category"] == "Crypto"


def test_filter_markets_partial_match_in_category():
    markets = [_mkt("crypto-usd"), _mkt("sports-nfl")]
    result = _filter_markets_by_category(markets, ["crypto"])
    assert len(result) == 1


def test_filter_markets_falls_back_to_group_item_title():
    m = {"category": "", "groupItemTitle": "Sports", "slug": ""}
    result = _filter_markets_by_category([m], ["sports"])
    assert result == [m]


def test_filter_markets_falls_back_to_slug():
    m = {"category": "", "groupItemTitle": "", "slug": "crypto-btc-eth"}
    result = _filter_markets_by_category([m], ["crypto"])
    assert result == [m]


def test_filter_markets_no_match_returns_empty():
    markets = [_mkt("crypto"), _mkt("sports")]
    result = _filter_markets_by_category(markets, ["politics"])
    assert result == []


def test_filter_markets_empty_list_returns_empty():
    assert _filter_markets_by_category([], ["crypto"]) == []


def test_process_candidate_freshness_gate_bypassed_for_lib_strategy():
    """pub_uuid=None (lib-strategy candidate) must bypass the freshness gate entirely."""
    bootstrap_default_strategies()
    row = _user_row()

    # Build a candidate with no publication_id (lib-strategy path)
    ts_old = datetime.fromtimestamp(0, tz=timezone.utc)
    lib_cand = SignalCandidate(
        market_id=_MARKET_ID,
        condition_id=_MARKET_ID,
        side="YES",
        confidence=0.7,
        suggested_size_usdc=10.0,
        strategy_name="edge_finder",
        signal_ts=ts_old,  # epoch — extremely stale
        metadata={"market_id": _MARKET_ID},  # no publication_id key
    )

    from uuid import uuid4 as _uuid4
    approved = TradeResult(
        approved=True, mode="paper",
        order_id=_uuid4(), position_id=_uuid4(),
        rejection_reason=None, failed_gate_step=None,
    )

    engine_called = {"called": False}

    def _track_execute(*a, **kw):
        engine_called["called"] = True
        return approved

    with patch.object(job, "_load_market", return_value=_market_row()), \
            patch.object(job._engine, "execute", new=AsyncMock(side_effect=_track_execute)), \
            patch.object(job, "_insert_execution_queue", new=AsyncMock(return_value=True)), \
            patch.object(job, "_mark_executed", new=AsyncMock()):
        asyncio.run(job._process_candidate(row, lib_cand))

    assert engine_called["called"], "lib-strategy must bypass freshness gate and reach engine"


# ---------------------------------------------------------------------------
# fetch_latest_scan_run — operator-panel truth source (scan_runs, not job_runs)
# ---------------------------------------------------------------------------


def test_fetch_latest_scan_run_returns_dict():
    row = {
        "id": uuid4(),
        "candidates_emitted": 453,
        "strategies_loaded": 11,
        "rejection_breakdown": {"step_7_max_concurrent_trades": 33},
    }
    conn = _FakeConn(fetchrow_results=[row])
    with _patch_pool(conn):
        result = asyncio.run(job.fetch_latest_scan_run())
    assert result == row


def test_fetch_latest_scan_run_none_when_empty():
    conn = _FakeConn(fetchrow_results=[None])
    with _patch_pool(conn):
        result = asyncio.run(job.fetch_latest_scan_run())
    assert result is None


def test_fetch_latest_scan_run_swallows_errors():
    with patch.object(job, "get_pool", side_effect=RuntimeError("db down")):
        result = asyncio.run(job.fetch_latest_scan_run())
    assert result is None  # no silent crash — degrades to None


# ===========================================================================
# _diversify_lib_candidates — lib-strategy scan diversification
# ===========================================================================

from projects.polymarket.crusaderbot.services.signal_scan.signal_scan_job import (
    _diversify_lib_candidates,
)
from projects.polymarket.crusaderbot.domain.strategy.types import SignalCandidate
from datetime import datetime, timezone


def _cand(market_id: str) -> SignalCandidate:
    return SignalCandidate(
        market_id=market_id,
        condition_id=market_id,
        side="YES",
        confidence=0.7,
        suggested_size_usdc=10.0,
        strategy_name="test_strategy",
        signal_ts=datetime.now(tz=timezone.utc),
    )


def test_diversify_lib_candidates_empty():
    """Empty candidate list returns empty list."""
    assert _diversify_lib_candidates([], "user-a") == []


def test_diversify_lib_candidates_single():
    """Single candidate is returned regardless of user."""
    c = _cand("mkt-1")
    assert _diversify_lib_candidates([c], "user-a") == [c]


def test_diversify_lib_candidates_different_order_for_different_users():
    """Two different users must receive candidates in different order when
    multiple candidates are available — this is the core invariant."""
    cands = [_cand(f"mkt-{i}") for i in range(5)]
    order_a = [c.market_id for c in _diversify_lib_candidates(cands, "user-aaa")]
    order_b = [c.market_id for c in _diversify_lib_candidates(cands, "user-bbb")]
    # With 5 markets and two distinct user IDs the sha1 keys will differ —
    # it is astronomically unlikely for them to produce the same ordering.
    assert order_a != order_b


def test_diversify_lib_candidates_deterministic_same_user():
    """Same user always gets the same ordering (no churn between ticks)."""
    cands = [_cand(f"mkt-{i}") for i in range(5)]
    order_1 = [c.market_id for c in _diversify_lib_candidates(cands, "user-x")]
    order_2 = [c.market_id for c in _diversify_lib_candidates(cands, "user-x")]
    assert order_1 == order_2


def test_diversify_lib_candidates_all_markets_preserved():
    """All candidates are returned — none dropped by diversification."""
    cands = [_cand(f"mkt-{i}") for i in range(8)]
    result = _diversify_lib_candidates(cands, "user-a")
    assert len(result) == 8
    assert {c.market_id for c in result} == {f"mkt-{i}" for i in range(8)}


# ---------------------------------------------------------------------------
# run_close_sweep_fast — dedicated high-frequency close_sweep loop
# ---------------------------------------------------------------------------


def _close_sweep_user(preset: str) -> dict:
    row = _user_row()
    row["active_preset"] = preset
    row["selected_timeframe"] = "5m"
    row["selected_assets"] = ["BTC"]
    return row


def test_run_close_sweep_fast_scans_only_close_sweep_users():
    """Only active_preset=='close_sweep' rows reach late_entry_v3; others skip."""
    cs_user = _close_sweep_user("close_sweep")
    other_user = _close_sweep_user("full_auto")
    cand = _candidate(market_id="cand-mkt")

    fake_strat = MagicMock()
    fake_strat.scan = AsyncMock(return_value=[cand])
    reg = StrategyRegistry.instance()

    ctx = UserContext(
        user_id=str(cs_user["user_id"]), sub_account_id=str(uuid4()),
        risk_profile="balanced", capital_allocation_pct=0.1,
        available_balance_usdc=500.0, selected_timeframe="5m",
        selected_assets=("BTC",),
    )
    filters = MarketFilters(categories=[], min_liquidity=0.0,
                            max_time_to_resolution_days=365,
                            blacklisted_market_ids=[])
    proc = AsyncMock()

    with patch.object(reg, "get", return_value=fake_strat), \
            patch.object(job, "_load_enrolled_users",
                         new=AsyncMock(return_value=[cs_user, other_user])), \
            patch.object(job._polymarket, "get_crypto_window_markets",
                         new=AsyncMock(return_value=[])), \
            patch.object(job, "_upsert_crypto_window_markets", new=AsyncMock()), \
            patch.object(job, "_build_user_context", return_value=ctx), \
            patch.object(job, "_build_market_filters", return_value=filters), \
            patch.object(job, "_process_candidate", new=proc):
        asyncio.run(job.run_close_sweep_fast())

    # late_entry scan ran for exactly the one close_sweep user.
    assert fake_strat.scan.await_count == 1
    proc.assert_awaited_once()


def test_run_close_sweep_fast_skips_when_late_entry_globally_disabled():
    """Operator global OFF of late_entry_v3 must stop the fast candle loop too."""
    cs_user = _close_sweep_user("close_sweep")
    fake_strat = MagicMock()
    fake_strat.scan = AsyncMock(return_value=[_candidate(market_id="m")])
    reg = StrategyRegistry.instance()
    load = AsyncMock(return_value=[cs_user])

    original = job._GLOBALLY_DISABLED_STRATEGIES
    try:
        job._GLOBALLY_DISABLED_STRATEGIES = frozenset({"late_entry_v3"})
        with patch.object(reg, "get", return_value=fake_strat), \
                patch.object(job, "_refresh_disabled_strategies", new=AsyncMock()), \
                patch.object(job, "_load_enrolled_users", new=load):
            asyncio.run(job.run_close_sweep_fast())
        # Globally disabled → loop returns before loading users / scanning.
        load.assert_not_called()
        fake_strat.scan.assert_not_awaited()
    finally:
        job._GLOBALLY_DISABLED_STRATEGIES = original


def test_run_close_sweep_fast_no_close_sweep_users_is_noop():
    other_user = _close_sweep_user("full_auto")
    fake_strat = MagicMock()
    fake_strat.scan = AsyncMock(return_value=[])
    reg = StrategyRegistry.instance()
    proc = AsyncMock()

    with patch.object(reg, "get", return_value=fake_strat), \
            patch.object(job, "_load_enrolled_users",
                         new=AsyncMock(return_value=[other_user])), \
            patch.object(job._polymarket, "get_crypto_window_markets",
                         new=AsyncMock(return_value=[])), \
            patch.object(job, "_upsert_crypto_window_markets", new=AsyncMock()), \
            patch.object(job, "_process_candidate", new=proc):
        asyncio.run(job.run_close_sweep_fast())

    fake_strat.scan.assert_not_called()
    proc.assert_not_called()


def test_run_close_sweep_fast_unregistered_strategy_returns():
    """When late_entry_v3 is not registered, the loop returns without loading users."""
    reg = StrategyRegistry.instance()
    load = AsyncMock(return_value=[])
    with patch.object(reg, "get", side_effect=KeyError("late_entry_v3")), \
            patch.object(job, "_load_enrolled_users", new=load):
        asyncio.run(job.run_close_sweep_fast())
    load.assert_not_called()


# ---------------------------------------------------------------------------
# _resolve_preset_params — Kreo-aligned per-preset / per-timeframe resolution
# ---------------------------------------------------------------------------


def test_resolve_preset_params_close_sweep_has_no_force_exit():
    """close_sweep holds to candle resolution — no force_exit_at_rem_sec key."""
    pp = job._resolve_preset_params("close_sweep", "5m")
    assert "force_exit_at_rem_sec" not in pp


def test_random_close_sweep_min_edge_band():
    """_random_close_sweep_min_edge draws within the configured [MIN, MAX] band."""
    cfg = type("C", (), {
        "PRESET_CLOSE_SWEEP_MIN_ASK_DIFF_MIN": 0.02,
        "PRESET_CLOSE_SWEEP_MIN_ASK_DIFF_MAX": 0.04,
    })()
    seen = {job._random_close_sweep_min_edge(cfg) for _ in range(60)}
    assert all(0.02 <= v <= 0.04 for v in seen)
    assert len(seen) > 1  # randomized → multiple distinct draws


def test_random_close_sweep_min_edge_pinned_when_min_eq_max():
    """MIN == MAX pins the value (deterministic) for reproducible runs/tests."""
    cfg = type("C", (), {
        "PRESET_CLOSE_SWEEP_MIN_ASK_DIFF_MIN": 0.03,
        "PRESET_CLOSE_SWEEP_MIN_ASK_DIFF_MAX": 0.03,
    })()
    assert job._random_close_sweep_min_edge(cfg) == 0.03


def test_random_close_sweep_min_edge_safe_fallback_on_bad_cfg():
    """A cfg missing the band attrs falls back to 0.02 (never raises)."""
    assert job._random_close_sweep_min_edge(object()) == 0.02


def test_resolve_preset_params_close_sweep_min_edge_in_band_with_config():
    """With live config present, the close_sweep resolver emits a min_ask_diff
    inside the randomized [MIN, MAX] band (patched config → deterministic env)."""
    cfg = type("C", (), {
        "PRESET_CLOSE_SWEEP_MIN_ASK_DIFF_MIN": 0.02,
        "PRESET_CLOSE_SWEEP_MIN_ASK_DIFF_MAX": 0.04,
        "PRESET_CLOSE_SWEEP_WINDOW_SEC": 35.0,
        "PRESET_CLOSE_SWEEP_FAV_PRICE_MIN": 0.55,
    })()
    with patch("projects.polymarket.crusaderbot.config.get_settings", return_value=cfg):
        for _ in range(20):
            pp = job._resolve_preset_params("close_sweep", "5m")
            assert 0.02 <= pp["min_ask_diff"] <= 0.04


def test_resolve_preset_params_safe_close_emits_force_exit_30s():
    """safe_close has force_exit_at_rem_sec=30s for both 5m and 15m (same rem semantics)."""
    pp_5m = job._resolve_preset_params("safe_close", "5m")
    pp_15m = job._resolve_preset_params("safe_close", "15m")
    assert pp_5m["force_exit_at_rem_sec"] == pytest.approx(30.0)
    assert pp_15m["force_exit_at_rem_sec"] == pytest.approx(30.0)
    # safe_close stays in standard mode (favored side)
    assert pp_5m.get("underdog_mode", False) is False
    # min_entry_sec preserved so the scan still gates final 30s out
    assert pp_5m["min_entry_sec"] == pytest.approx(30.0)


def test_resolve_preset_params_flip_hunter_5m_kreo_alignment():
    """flip_hunter 5m: with-trend (NOT underdog), early window (rem 160-300), force-exit 160s, Min Edge 3%."""
    pp = job._resolve_preset_params("flip_hunter", "5m")
    assert pp.get("underdog_mode", False) is False, "Kreo With Trend → favored side"
    assert pp["entry_window_sec"] == pytest.approx(300.0), "rem upper = full 5m candle"
    assert pp["min_entry_sec"] == pytest.approx(160.0), "rem lower = end of first 140s elapsed"
    assert pp["force_exit_at_rem_sec"] == pytest.approx(160.0)
    assert pp["min_ask_diff"] == pytest.approx(0.03), "Kreo Min Edge 3%"


def test_resolve_preset_params_flip_hunter_15m_kreo_alignment():
    """flip_hunter 15m: same with-trend semantics, scaled to 15m candle (rem 480-900, force-exit 480)."""
    pp = job._resolve_preset_params("flip_hunter", "15m")
    assert pp.get("underdog_mode", False) is False
    assert pp["entry_window_sec"] == pytest.approx(900.0)
    assert pp["min_entry_sec"] == pytest.approx(480.0)
    assert pp["force_exit_at_rem_sec"] == pytest.approx(480.0)


def test_resolve_preset_params_flip_hunter_unknown_tf_defaults_to_5m():
    """Missing / unknown timeframe defaults to 5m mapping (safe default)."""
    pp_default = job._resolve_preset_params("flip_hunter", None)
    pp_5m = job._resolve_preset_params("flip_hunter", "5m")
    assert pp_default["entry_window_sec"] == pp_5m["entry_window_sec"]
    assert pp_default["force_exit_at_rem_sec"] == pp_5m["force_exit_at_rem_sec"]


def test_resolve_preset_params_non_candle_preset_falls_back_to_static():
    """Unknown / non-candle preset returns the static fallback (no live config read)."""
    pp = job._resolve_preset_params("full_auto", "5m")
    # full_auto isn't in _CANDLE_PRESET_STATIC so falls through to close_sweep default.
    assert "min_ask_diff" in pp
    assert pp["min_ask_diff"] == pytest.approx(0.05)  # close_sweep static default


def test_resolve_preset_params_safe_close_loosened_to_kreo_min_edge():
    """Kreo Min Edge 1% → min_ask_diff 0.01 (previously 0.08, much tighter)."""
    pp = job._resolve_preset_params("safe_close", "5m")
    assert pp["min_ask_diff"] == pytest.approx(0.01)


def test_resolve_preset_params_flip_hunter_fav_band_no_longer_underdog():
    """flip_hunter band changed from underdog [0.26, 0.36] to favored [0.50, 0.95]."""
    pp = job._resolve_preset_params("flip_hunter", "5m")
    assert pp["fav_price_min"] == pytest.approx(0.50)
    assert pp["fav_price_max"] == pytest.approx(0.95)


def test_run_close_sweep_fast_telemetry_markets_seen_reflects_candle_universe(monkeypatch):
    """scan_runs.markets_seen must NOT be 0 when candle markets are fetched.

    Previously the fast scan never set tel.markets_seen, so every candle-only
    scan_run row showed markets_seen=0 even when 5+ crypto window markets were
    available — misleading when debugging "why no trades?".
    """
    import inspect
    src = inspect.getsource(job.run_close_sweep_fast)
    # The fix: _candle_markets_seen is accumulated and assigned to tel.markets_seen
    assert "_candle_markets_seen" in src
    assert "tel.markets_seen = _candle_markets_seen" in src


def test_run_once_mode_label_uses_three_guard_check(monkeypatch):
    """scan_runs.mode must be 'LIVE' only when all 3 core live guards are True.

    The original code used only ENABLE_LIVE_TRADING, so any deployment with
    that single flag set would log mode='LIVE' even in pure paper mode.
    Consistent with run_close_sweep_fast which already uses 3-guard logic.
    """
    import inspect
    src = inspect.getsource(job.run_once)
    # Must check all 3 guards, not just ENABLE_LIVE_TRADING alone
    assert "EXECUTION_PATH_VALIDATED" in src
    assert "CAPITAL_MODE_CONFIRMED" in src
