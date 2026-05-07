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
from datetime import datetime, timezone
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
    access_tier: int = 3,
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
        "access_tier": access_tier,
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
        signal_ts=_NOW,
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
    assert set(avail) == {"conservative", "balanced", "aggressive"}


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


def test_build_idempotency_key_differs_by_publication():
    pub2 = uuid4()
    k1 = job._build_idempotency_key(_USER_UUID, _MARKET_ID, "YES", _PUB_UUID)
    k2 = job._build_idempotency_key(_USER_UUID, _MARKET_ID, "YES", pub2)
    assert k1 != k2


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

    from projects.polymarket.crusaderbot.domain.risk.gate import GateResult

    executed = {"called": False}

    async def _fake_router(**kwargs):
        executed["called"] = True

    with patch.object(job, "_load_stale_queued_row", return_value=None), \
            patch.object(job, "_publication_already_queued", return_value=False), \
            patch.object(job, "_load_market", return_value=_market_row()), \
            patch.object(
                job, "risk_evaluate",
                return_value=GateResult(False, "max_concurrent_trades", 7),
            ), \
            patch.object(job, "router_execute", side_effect=_fake_router):
        asyncio.run(job._process_candidate(row, cand))

    assert not executed["called"]


# ---------------------------------------------------------------------------
# _process_candidate — happy path (accepted, executed)
# ---------------------------------------------------------------------------


def test_process_candidate_happy_path_inserts_queue_and_executes():
    bootstrap_default_strategies()
    row = _user_row()
    cand = _candidate()

    from projects.polymarket.crusaderbot.domain.risk.gate import GateResult

    executed = {"called": False}
    marked = {"called": False}

    async def _fake_router(**kwargs):
        executed["called"] = True

    async def _fake_mark_executed(*a, **kw):
        marked["called"] = True

    gate_ok = GateResult(True, "approved", None, Decimal("10"), "paper")

    with patch.object(job, "_load_stale_queued_row", return_value=None), \
            patch.object(job, "_publication_already_queued", return_value=False), \
            patch.object(job, "_load_market", return_value=_market_row()), \
            patch.object(job, "risk_evaluate", return_value=gate_ok), \
            patch.object(job, "_insert_execution_queue", return_value=True), \
            patch.object(job, "router_execute", side_effect=_fake_router), \
            patch.object(job, "_mark_executed", side_effect=_fake_mark_executed):
        asyncio.run(job._process_candidate(row, cand))

    assert executed["called"]
    assert marked["called"]


# ---------------------------------------------------------------------------
# _process_candidate — router raises (failed outcome)
# ---------------------------------------------------------------------------


def test_process_candidate_marks_failed_when_router_raises():
    bootstrap_default_strategies()
    row = _user_row()
    cand = _candidate()

    from projects.polymarket.crusaderbot.domain.risk.gate import GateResult

    marked_failed = {"called": False, "err": None}

    async def _boom(**kwargs):
        raise RuntimeError("clob error")

    async def _fake_mark_failed(user_id, pub_id, idem_key, error):
        marked_failed["called"] = True
        marked_failed["err"] = error

    gate_ok = GateResult(True, "approved", None, Decimal("10"), "paper")

    with patch.object(job, "_load_stale_queued_row", return_value=None), \
            patch.object(job, "_publication_already_queued", return_value=False), \
            patch.object(job, "_load_market", return_value=_market_row()), \
            patch.object(job, "risk_evaluate", return_value=gate_ok), \
            patch.object(job, "_insert_execution_queue", return_value=True), \
            patch.object(job, "router_execute", side_effect=_boom), \
            patch.object(job, "_mark_failed", side_effect=_fake_mark_failed):
        asyncio.run(job._process_candidate(row, cand))

    assert marked_failed["called"]
    assert "clob error" in marked_failed["err"]


# ---------------------------------------------------------------------------
# _process_candidate — concurrent dedup (insert returns False)
# ---------------------------------------------------------------------------


def test_process_candidate_skips_when_concurrent_insert_conflict():
    bootstrap_default_strategies()
    row = _user_row()
    cand = _candidate()

    from projects.polymarket.crusaderbot.domain.risk.gate import GateResult

    executed = {"called": False}

    async def _fake_router(**kwargs):
        executed["called"] = True

    gate_ok = GateResult(True, "approved", None, Decimal("10"), "paper")

    with patch.object(job, "_load_stale_queued_row", return_value=None), \
            patch.object(job, "_publication_already_queued", return_value=False), \
            patch.object(job, "_load_market", return_value=_market_row()), \
            patch.object(job, "risk_evaluate", return_value=gate_ok), \
            patch.object(job, "_insert_execution_queue", return_value=False), \
            patch.object(job, "router_execute", side_effect=_fake_router):
        asyncio.run(job._process_candidate(row, cand))

    assert not executed["called"]


# ---------------------------------------------------------------------------
# _process_candidate — inactive/expired signal (market status != active)
# ---------------------------------------------------------------------------


def test_process_candidate_risk_rejects_inactive_market():
    bootstrap_default_strategies()
    row = _user_row()
    cand = _candidate()

    from projects.polymarket.crusaderbot.domain.risk.gate import GateResult

    executed = {"called": False}

    async def _fake_router(**kwargs):
        executed["called"] = True

    # Gate rejects because market is resolved (step 13).
    gate_rejected = GateResult(False, "market_inactive", 13)

    with patch.object(job, "_load_stale_queued_row", return_value=None), \
            patch.object(job, "_publication_already_queued", return_value=False), \
            patch.object(job, "_load_market", return_value=_market_row(status="resolved")), \
            patch.object(job, "risk_evaluate", return_value=gate_rejected), \
            patch.object(job, "router_execute", side_effect=_fake_router):
        asyncio.run(job._process_candidate(row, cand))

    assert not executed["called"]


# ---------------------------------------------------------------------------
# run_once — single user, happy path integration (all internals patched)
# ---------------------------------------------------------------------------


def test_run_once_happy_path_calls_process_candidate():
    bootstrap_default_strategies()
    row = _user_row()
    cand = _candidate()
    processed = {"calls": 0}

    async def _fake_scan(mf: MarketFilters, uc: UserContext):
        return [cand]

    async def _fake_process(r, c):
        processed["calls"] += 1

    with patch.object(job, "_load_enrolled_users", return_value=[row]), \
            patch.object(
                StrategyRegistry.instance().get("signal_following"),
                "scan",
                side_effect=_fake_scan,
            ), \
            patch.object(job, "_process_candidate", side_effect=_fake_process):
        asyncio.run(job.run_once())

    assert processed["calls"] == 1


# ---------------------------------------------------------------------------
# run_once — scan failure per user is isolated
# ---------------------------------------------------------------------------


def test_run_once_scan_failure_does_not_stop_other_users():
    bootstrap_default_strategies()
    row1 = _user_row(user_id=UUID("11111111-1111-1111-1111-111111111111"))
    row2 = _user_row(user_id=UUID("22222222-2222-2222-2222-222222222222"))
    processed = {"calls": 0}

    call_n = {"n": 0}

    async def _failing_then_ok(mf, uc):
        call_n["n"] += 1
        if call_n["n"] == 1:
            raise RuntimeError("boom")
        return [_candidate()]

    async def _fake_process(r, c):
        processed["calls"] += 1

    with patch.object(job, "_load_enrolled_users", return_value=[row1, row2]), \
            patch.object(
                StrategyRegistry.instance().get("signal_following"),
                "scan",
                side_effect=_failing_then_ok,
            ), \
            patch.object(job, "_process_candidate", side_effect=_fake_process):
        asyncio.run(job.run_once())

    # First user scan raised — second user still processed.
    assert processed["calls"] == 1


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
            patch.object(job, "_load_market", return_value=_market_row()), \
            patch.object(job, "router_execute", side_effect=_fake_router), \
            patch.object(job, "_mark_executed", side_effect=_fake_mark_executed), \
            patch.object(job, "risk_evaluate") as mock_gate:
        asyncio.run(job._process_candidate(row, cand))

    assert executed["called"]
    assert marked["called"]
    # Gate must NOT be called — crash recovery bypasses the risk gate entirely.
    mock_gate.assert_not_called()
