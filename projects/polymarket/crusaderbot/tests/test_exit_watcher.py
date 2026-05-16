"""Tests for the R12c exit watcher.

Hermetic: no DB, no broker, no Telegram. Patches:
  * ``registry`` functions to drive the position-fetch + state-mutation
    surface deterministically.
  * ``order.submit_close_with_retry`` indirectly via a fake submitter so
    we exercise success / first-fail-then-ok / always-fail paths without
    ``asyncio.sleep`` ever blocking the test (a no-op sleep stub is wired
    where the retry path is exercised directly).
  * ``monitoring.alerts.notifications.send`` so user-side alerts are
    captured rather than dispatched.

Coverage targets (from R12c task header):
  - TP hit → close + tp_hit user alert
  - SL hit → close + sl_hit user alert
  - force_close_intent=true → immediate close, force_close reason
  - force_close has priority over TP
  - CLOB error → retry once, on second failure: failure_count++, user
    + operator alerted
  - applied_* immutable: registry exposes no setter (structural test)
  - User /settings update path does not affect open positions: evaluate()
    only reads applied_*, ignores any tp_pct/sl_pct on the position dict
  - Resolved markets are skipped
  - Per-position exception isolated — does not poison the batch
"""
from __future__ import annotations

import asyncio
import inspect
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest

from projects.polymarket.crusaderbot.domain.execution import (
    exit_watcher,
    order as order_module,
)
from projects.polymarket.crusaderbot.domain.positions import registry
from projects.polymarket.crusaderbot.domain.positions.registry import (
    ExitReason,
    OpenPositionForExit,
)
from projects.polymarket.crusaderbot.monitoring import alerts as monitoring_alerts


def _run(coro):
    return asyncio.run(coro)


def _make_position(
    *,
    side: str = "yes",
    entry_price: float = 0.40,
    yes_price: float | None = 0.40,
    no_price: float | None = 0.60,
    applied_tp_pct: float | None = 0.20,
    applied_sl_pct: float | None = 0.10,
    force_close_intent: bool = False,
    close_failure_count: int = 0,
    market_resolved: bool = False,
    mode: str = "paper",
    position_id: UUID | None = None,
    user_id: UUID | None = None,
    market_question: str | None = "Will X happen?",
) -> OpenPositionForExit:
    return OpenPositionForExit(
        id=position_id or uuid4(),
        user_id=user_id or uuid4(),
        telegram_user_id=12345,
        market_id="MKT-1",
        market_question=market_question,
        side=side,
        entry_price=entry_price,
        size_usdc=100.0,
        mode=mode,
        status="open",
        applied_tp_pct=applied_tp_pct,
        applied_sl_pct=applied_sl_pct,
        force_close_intent=force_close_intent,
        close_failure_count=close_failure_count,
        yes_price=yes_price,
        no_price=no_price,
        market_resolved=market_resolved,
    )


# ---------------------------------------------------------------------------
# evaluate(): pure decision logic, no DB / network.
# ---------------------------------------------------------------------------

def test_evaluate_hold_when_inside_thresholds():
    """Mark price unchanged from entry: ret=0, neither TP nor SL trips."""
    p = _make_position(yes_price=0.40)
    decision = _run(exit_watcher.evaluate(p))
    assert not decision.should_exit
    assert decision.reason is None
    assert decision.current_price == pytest.approx(0.40)


def test_evaluate_tp_hit_yes_side():
    """YES side: ret = (cur - entry) / entry. cur=0.50 entry=0.40 -> +25% > 20%."""
    p = _make_position(yes_price=0.50, applied_tp_pct=0.20)
    decision = _run(exit_watcher.evaluate(p))
    assert decision.should_exit
    assert decision.reason == ExitReason.TP_HIT.value
    assert decision.current_price == pytest.approx(0.50)


def test_evaluate_sl_hit_yes_side():
    """YES side: cur=0.32 entry=0.40 -> -20%. SL=0.10 -> trips."""
    p = _make_position(yes_price=0.32, applied_sl_pct=0.10,
                       applied_tp_pct=0.50)
    decision = _run(exit_watcher.evaluate(p))
    assert decision.should_exit
    assert decision.reason == ExitReason.SL_HIT.value


def test_evaluate_tp_hit_no_side():
    """NO side P&L: (entry - cur)/(1-entry). entry=0.60 cur=0.50 -> +25%."""
    p = _make_position(side="no", entry_price=0.60,
                       yes_price=0.50, no_price=0.50,
                       applied_tp_pct=0.20)
    decision = _run(exit_watcher.evaluate(p))
    assert decision.should_exit
    assert decision.reason == ExitReason.TP_HIT.value


def test_evaluate_force_close_intent_overrides_tp():
    """force_close_intent must win even when TP is also breached."""
    p = _make_position(yes_price=0.99, applied_tp_pct=0.10,
                       force_close_intent=True)
    decision = _run(exit_watcher.evaluate(p))
    assert decision.should_exit
    assert decision.reason == ExitReason.FORCE_CLOSE.value


def test_evaluate_force_close_intent_overrides_sl():
    """force_close_intent must win even when SL is also breached."""
    p = _make_position(yes_price=0.01, applied_sl_pct=0.10,
                       force_close_intent=True)
    decision = _run(exit_watcher.evaluate(p))
    assert decision.should_exit
    assert decision.reason == ExitReason.FORCE_CLOSE.value


def test_evaluate_resolved_market_skipped():
    """Resolved markets are NOT closed by the watcher — redemption pipeline."""
    p = _make_position(yes_price=0.99, applied_tp_pct=0.05,
                       market_resolved=True)
    decision = _run(exit_watcher.evaluate(p))
    assert not decision.should_exit


def test_evaluate_strategy_exit_runs_after_sl():
    """Strategy hook only fires when force/TP/SL all hold."""
    calls: list[OpenPositionForExit] = []

    async def _strategy(pos):
        calls.append(pos)
        return True

    p = _make_position(yes_price=0.40)
    decision = _run(exit_watcher.evaluate(p, strategy_evaluator=_strategy))
    assert decision.should_exit
    assert decision.reason == ExitReason.STRATEGY_EXIT.value
    assert calls == [p]


def test_evaluate_ignores_tp_pct_when_applied_is_none():
    """User edits to user_settings.tp_pct must NOT bleed into open positions.

    The position carries no applied_* snapshot here, simulating the case
    where no TP was set at entry. The watcher must not invent a TP from
    elsewhere — it just holds.
    """
    p = _make_position(yes_price=0.99, applied_tp_pct=None,
                       applied_sl_pct=None)
    decision = _run(exit_watcher.evaluate(p))
    assert not decision.should_exit


# ---------------------------------------------------------------------------
# submit_close_with_retry: success / fail-then-ok / always-fail.
# ---------------------------------------------------------------------------

def test_close_with_retry_success_first_attempt():
    calls: list[dict] = []

    async def _ok(*, position, exit_price, exit_reason):
        calls.append({"reason": exit_reason})
        return {"pnl_usdc": 5.0}

    async def _no_sleep(_seconds):
        return None

    result = _run(order_module.submit_close_with_retry(
        position={"id": uuid4(), "mode": "paper"},
        exit_price=0.5, exit_reason="tp_hit",
        submitter=_ok, sleep=_no_sleep,
    ))
    assert result.ok is True
    assert result.payload == {"pnl_usdc": 5.0}
    assert result.error is None
    assert len(calls) == 1


def test_close_with_retry_fails_then_succeeds_paper_mode():
    """Paper mode retries: errors are DB-only and safe to repeat."""
    attempts = [0]

    async def _flaky(*, position, exit_price, exit_reason):
        attempts[0] += 1
        if attempts[0] == 1:
            raise RuntimeError("asyncpg transient")
        return {"pnl_usdc": 0.0}

    sleeps: list[float] = []

    async def _record_sleep(seconds):
        sleeps.append(seconds)

    result = _run(order_module.submit_close_with_retry(
        position={"id": uuid4(), "mode": "paper"},
        exit_price=0.5, exit_reason="tp_hit",
        submitter=_flaky, sleep=_record_sleep,
    ))
    assert result.ok is True
    assert attempts[0] == 2
    assert sleeps == [order_module.CLOSE_RETRY_DELAY_SECONDS]


def test_close_with_retry_paper_exhausts_then_fails():
    attempts = [0]

    async def _always_fail(*, position, exit_price, exit_reason):
        attempts[0] += 1
        raise RuntimeError("clob down")

    async def _no_sleep(_seconds):
        return None

    result = _run(order_module.submit_close_with_retry(
        position={"id": uuid4(), "mode": "paper"},
        exit_price=0.5, exit_reason="tp_hit",
        submitter=_always_fail, sleep=_no_sleep,
    ))
    assert result.ok is False
    assert attempts[0] == order_module.PAPER_CLOSE_MAX_ATTEMPTS
    assert "clob down" in (result.error or "")


def test_close_with_retry_live_mode_does_not_retry_on_failure():
    """Capital safety: live mode submit failures are post-submit ambiguous —
    a retry could place a duplicate on-chain SELL. The helper must make
    a single attempt only and surface the failure to the caller.
    """
    attempts = [0]

    async def _ambiguous_fail(*, position, exit_price, exit_reason):
        attempts[0] += 1
        # Mimics a network timeout AFTER the broker queued the SELL —
        # cannot be safely retried without risking double-close.
        raise RuntimeError("clob ack timeout")

    sleeps: list[float] = []

    async def _record_sleep(seconds):
        sleeps.append(seconds)

    result = _run(order_module.submit_close_with_retry(
        position={"id": uuid4(), "mode": "live"},
        exit_price=0.5, exit_reason="tp_hit",
        submitter=_ambiguous_fail, sleep=_record_sleep,
    ))
    assert result.ok is False
    assert attempts[0] == 1, (
        "live mode must NOT retry — duplicate on-chain SELL risk"
    )
    assert sleeps == [], "no inter-attempt sleep when retry is disallowed"
    assert "clob ack timeout" in (result.error or "")
    assert order_module.LIVE_CLOSE_MAX_ATTEMPTS == 1


def test_close_with_retry_live_mode_success_first_attempt_unchanged():
    """Live mode is no-retry on FAILURE, but a successful first attempt
    behaves identically to paper.
    """
    attempts = [0]

    async def _ok(*, position, exit_price, exit_reason):
        attempts[0] += 1
        return {"pnl_usdc": 5.0, "exit_price": exit_price}

    async def _no_sleep(_seconds):
        return None

    result = _run(order_module.submit_close_with_retry(
        position={"id": uuid4(), "mode": "live"},
        exit_price=0.5, exit_reason="tp_hit",
        submitter=_ok, sleep=_no_sleep,
    ))
    assert result.ok is True
    assert attempts[0] == 1


def test_close_max_attempts_alias_matches_paper_budget():
    """Backwards-compat alias must continue to mean the paper budget so
    callers that imported the original constant keep working.
    """
    assert order_module.CLOSE_MAX_ATTEMPTS == order_module.PAPER_CLOSE_MAX_ATTEMPTS


# ---------------------------------------------------------------------------
# run_once: orchestration — close path, hold path, failure path.
# ---------------------------------------------------------------------------

class _Captured:
    """Capture every alert function call so assertions can introspect."""

    def __init__(self):
        self.tp_hit: list[dict] = []
        self.sl_hit: list[dict] = []
        self.force_close: list[dict] = []
        self.strategy_exit: list[dict] = []
        self.close_failed_user: list[dict] = []
        self.close_failed_op: list[dict] = []


def _patch_alerts(captured: _Captured):
    """Patch all five alert functions with capturing async stubs."""

    async def _tp(**kw):
        captured.tp_hit.append(kw)

    async def _sl(**kw):
        captured.sl_hit.append(kw)

    async def _fc(**kw):
        captured.force_close.append(kw)

    async def _strat(**kw):
        captured.strategy_exit.append(kw)

    async def _cfu(**kw):
        captured.close_failed_user.append(kw)

    async def _cfo(**kw):
        captured.close_failed_op.append(kw)

    return [
        patch.object(monitoring_alerts, "alert_user_tp_hit", _tp),
        patch.object(monitoring_alerts, "alert_user_sl_hit", _sl),
        patch.object(monitoring_alerts, "alert_user_force_close", _fc),
        patch.object(monitoring_alerts, "alert_user_strategy_exit", _strat),
        patch.object(monitoring_alerts, "alert_user_close_failed", _cfu),
        patch.object(
            monitoring_alerts,
            "alert_operator_close_failed_persistent",
            _cfo,
        ),
    ]


def _patch_audit_noop():
    """Audit writes go nowhere in tests."""
    return patch(
        "projects.polymarket.crusaderbot.domain.execution.exit_watcher.audit.write",
        new=AsyncMock(),
    )


def _patch_registry(
    *,
    positions: list[OpenPositionForExit],
    record_failure_returns: int = 1,
):
    """Patch registry calls: list, record_close_failure, reset, update_price.

    ``_fetch_live_price`` is patched to return each position's own
    ``current_price()`` keyed by (market_id, side). This keeps tests hermetic
    (no Gamma API calls) while also preventing the MARKET_EXPIRED retry path
    from triggering — two consecutive None results would now close the position
    as expired and bypass TP/SL evaluation entirely.

    Phase B (``list_open_on_resolved_markets``) defaults to empty so existing
    tests are unaffected by the two-phase sweep.
    """
    record_failure = AsyncMock(return_value=record_failure_returns)
    reset_failure = AsyncMock(return_value=None)
    update_price = AsyncMock(return_value=None)
    close_expired_noop = AsyncMock(return_value=True)
    list_open = AsyncMock(return_value=positions)
    list_open_resolved = AsyncMock(return_value=[])

    pos_prices = {(p.market_id, p.side): p.current_price() for p in positions}

    async def _fetch_price(market_id: str, side: str) -> float | None:
        return pos_prices.get((market_id, side))

    return (
        record_failure, reset_failure, update_price, list_open,
        [
            patch.object(registry, "list_open_for_exit", list_open),
            patch.object(registry, "list_open_on_resolved_markets", list_open_resolved),
            patch.object(registry, "close_as_expired", close_expired_noop),
            patch.object(registry, "record_close_failure", record_failure),
            patch.object(registry, "reset_close_failure", reset_failure),
            patch.object(registry, "update_current_price", update_price),
            # Return actual position prices — no live HTTP calls to Gamma API.
            patch.object(exit_watcher, "_fetch_live_price", _fetch_price),
        ],
    )


def test_run_once_tp_hit_closes_and_alerts():
    captured = _Captured()
    pos = _make_position(yes_price=0.50, applied_tp_pct=0.20)
    closed: list[dict] = []

    async def _submitter(*, position, exit_price, exit_reason):
        closed.append({"id": position["id"], "reason": exit_reason,
                       "price": exit_price})
        return {"pnl_usdc": 5.0, "exit_price": exit_price,
                "exit_reason": exit_reason}

    (record_failure, reset_failure, update_price, list_open,
     reg_patches) = _patch_registry(positions=[pos])

    patches = (
        reg_patches
        + _patch_alerts(captured)
        + [_patch_audit_noop()]
    )
    for p_ in patches:
        p_.start()
    try:
        result = _run(exit_watcher.run_once(close_submitter=_submitter))
    finally:
        for p_ in patches:
            p_.stop()

    assert result.submitted == 1
    assert len(closed) == 1
    assert closed[0]["reason"] == ExitReason.TP_HIT.value
    assert len(captured.tp_hit) == 1
    assert captured.tp_hit[0]["pnl_usdc"] == pytest.approx(5.0)
    # No close_failure path: failure-counter helpers untouched.
    record_failure.assert_not_awaited()
    update_price.assert_not_awaited()


def test_run_once_sl_hit_alerts_user():
    captured = _Captured()
    pos = _make_position(yes_price=0.32, applied_sl_pct=0.10,
                         applied_tp_pct=0.50)

    async def _submitter(*, position, exit_price, exit_reason):
        return {"pnl_usdc": -20.0, "exit_price": exit_price,
                "exit_reason": exit_reason}

    (record_failure, reset_failure, update_price, list_open,
     reg_patches) = _patch_registry(positions=[pos])
    patches = reg_patches + _patch_alerts(captured) + [_patch_audit_noop()]
    for p_ in patches:
        p_.start()
    try:
        _run(exit_watcher.run_once(close_submitter=_submitter))
    finally:
        for p_ in patches:
            p_.stop()
    assert len(captured.sl_hit) == 1
    assert captured.sl_hit[0]["exit_price"] == pytest.approx(0.32)


def test_run_once_force_close_intent_executes_immediately():
    """force_close_intent overrides TP, lands as force_close reason."""
    captured = _Captured()
    pos = _make_position(yes_price=0.99, applied_tp_pct=0.10,
                         force_close_intent=True)
    closed: list[dict] = []

    async def _submitter(*, position, exit_price, exit_reason):
        closed.append({"reason": exit_reason})
        return {"pnl_usdc": 50.0, "exit_price": exit_price,
                "exit_reason": exit_reason}

    (record_failure, _r, _u, _l, reg_patches) = _patch_registry(positions=[pos])
    patches = reg_patches + _patch_alerts(captured) + [_patch_audit_noop()]
    for p_ in patches:
        p_.start()
    try:
        _run(exit_watcher.run_once(close_submitter=_submitter))
    finally:
        for p_ in patches:
            p_.stop()
    assert closed == [{"reason": ExitReason.FORCE_CLOSE.value}]
    assert len(captured.force_close) == 1
    # TP path must NOT fire when force_close wins.
    assert captured.tp_hit == []


def test_run_once_close_failure_increments_counter_and_alerts():
    """Close fails twice (initial + 1 retry) -> failure_count++,
    user alert suppressed (logger.info only), operator alerted at threshold."""
    captured = _Captured()
    pos = _make_position(yes_price=0.99, applied_tp_pct=0.10,
                         close_failure_count=1)

    async def _failing(*, position, exit_price, exit_reason):
        raise RuntimeError("CLOB 503 Service Unavailable")

    # record_close_failure returns 2 -> threshold met -> operator alert.
    (record_failure, reset_failure, update_price, list_open,
     reg_patches) = _patch_registry(positions=[pos],
                                    record_failure_returns=2)

    # Squash retry sleep so the test is fast.
    async def _no_sleep(_):
        return None

    patches = (
        reg_patches
        + _patch_alerts(captured)
        + [
            _patch_audit_noop(),
            patch.object(order_module, "asyncio",
                         new=type("S", (), {"sleep": _no_sleep})()),
        ]
    )
    for p_ in patches:
        p_.start()
    try:
        _run(exit_watcher.run_once(close_submitter=_failing))
    finally:
        for p_ in patches:
            p_.stop()

    record_failure.assert_awaited_once_with(pos.id, pos.user_id)
    # User alert suppressed — exit_watcher logs to logger.info instead.
    assert len(captured.close_failed_user) == 0
    # Operator alert dispatched because failure_count(=2) crossed threshold.
    assert len(captured.close_failed_op) == 1
    assert captured.close_failed_op[0]["failure_count"] == 2
    assert "CLOB 503" in captured.close_failed_op[0]["last_error"]
    # Position stays open: no reset, no terminal-state finalize on close failure.
    reset_failure.assert_not_awaited()


def test_run_once_live_close_failure_records_without_retry():
    """End-to-end watcher run: a live close that fails must NOT retry, but
    must still increment failure_count, suppress user alert (logger.info only),
    and alert the operator at threshold — proving the no-retry-on-live policy
    does not silence the failure path.
    """
    captured = _Captured()
    pos = _make_position(yes_price=0.99, applied_tp_pct=0.10,
                         mode="live", close_failure_count=1)
    submit_calls = [0]

    async def _live_fail(*, position, exit_price, exit_reason):
        submit_calls[0] += 1
        raise RuntimeError("clob 504 gateway timeout")

    (record_failure, reset_failure, update_price, list_open,
     reg_patches) = _patch_registry(positions=[pos],
                                    record_failure_returns=2)

    async def _no_sleep(_):
        return None

    patches = (
        reg_patches
        + _patch_alerts(captured)
        + [
            _patch_audit_noop(),
            patch.object(order_module, "asyncio",
                         new=type("S", (), {"sleep": _no_sleep})()),
        ]
    )
    for p_ in patches:
        p_.start()
    try:
        _run(exit_watcher.run_once(close_submitter=_live_fail))
    finally:
        for p_ in patches:
            p_.stop()

    assert submit_calls[0] == 1, (
        "live mode submit must be attempted exactly once — no retry"
    )
    record_failure.assert_awaited_once_with(pos.id, pos.user_id)
    # User alert suppressed — exit_watcher logs to logger.info instead.
    assert len(captured.close_failed_user) == 0
    assert len(captured.close_failed_op) == 1
    assert captured.close_failed_op[0]["mode"] == "live"


def test_run_once_hold_updates_current_price_only():
    """No exit triggered -> only current_price refreshed, no close, no alert."""
    captured = _Captured()
    pos = _make_position(yes_price=0.40, applied_tp_pct=0.50,
                         applied_sl_pct=0.50)
    submit_calls: list[Any] = []

    async def _submitter(*, position, exit_price, exit_reason):
        submit_calls.append(position)
        return {"pnl_usdc": 0.0}

    (record_failure, reset_failure, update_price, list_open,
     reg_patches) = _patch_registry(positions=[pos])
    patches = reg_patches + _patch_alerts(captured) + [_patch_audit_noop()]
    for p_ in patches:
        p_.start()
    try:
        result = _run(exit_watcher.run_once(close_submitter=_submitter))
    finally:
        for p_ in patches:
            p_.stop()
    assert result.submitted == 0
    assert submit_calls == []
    update_price.assert_awaited_once_with(
        pos.id, pytest.approx(0.40), pos.user_id, pnl_usdc=pytest.approx(0.0)
    )
    assert captured.tp_hit == captured.sl_hit == []


def test_run_once_per_position_failure_does_not_poison_batch():
    """A single bad row's exception must be logged and skipped, not raised
    out of the watcher. Subsequent positions in the same tick still
    evaluate normally.
    """
    captured = _Captured()
    bad = _make_position(yes_price=0.50, applied_tp_pct=0.20,
                         position_id=uuid4())
    good = _make_position(yes_price=0.50, applied_tp_pct=0.20,
                          position_id=uuid4())
    submitted: list[UUID] = []

    async def _submitter(*, position, exit_price, exit_reason):
        if position["id"] == bad.id:
            raise RuntimeError("simulated engine fault")
        submitted.append(position["id"])
        return {"pnl_usdc": 5.0}

    (record_failure, reset_failure, update_price, list_open,
     reg_patches) = _patch_registry(
         positions=[bad, good], record_failure_returns=1,
     )

    async def _no_sleep(_):
        return None

    patches = (
        reg_patches
        + _patch_alerts(captured)
        + [
            _patch_audit_noop(),
            patch.object(order_module, "asyncio",
                         new=type("S", (), {"sleep": _no_sleep})()),
        ]
    )
    for p_ in patches:
        p_.start()
    try:
        _run(exit_watcher.run_once(close_submitter=_submitter))
    finally:
        for p_ in patches:
            p_.stop()
    # The good position closed even though the bad one repeatedly failed.
    assert good.id in submitted
    # Bad position recorded a failure; user alert suppressed (logger.info only).
    record_failure.assert_awaited()
    assert len(captured.close_failed_user) == 0


# ---------------------------------------------------------------------------
# Snapshot-immutability: structural defence-in-depth.
# ---------------------------------------------------------------------------

def test_registry_exposes_no_applied_setter():
    """The registry surface MUST NOT expose any *function* (write path)
    that accepts ``applied_tp_pct`` / ``applied_sl_pct`` as a parameter.
    DB-level enforcement (trigger) is backed up by API-level enforcement
    here.

    The read-only ``OpenPositionForExit`` dataclass legitimately carries
    those snapshot fields — read paths must surface them so the watcher
    can evaluate TP/SL — so the scan excludes classes and only inspects
    callable functions / coroutines.
    """
    forbidden = {"applied_tp_pct", "applied_sl_pct"}
    for name in dir(registry):
        if name.startswith("_"):
            continue
        obj = getattr(registry, name)
        # Only scrutinise mutation entrypoints (functions / coroutines).
        # Classes and enums legitimately surface read-only snapshot fields.
        if not (inspect.isfunction(obj) or inspect.iscoroutinefunction(obj)):
            continue
        try:
            sig = inspect.signature(obj)
        except (TypeError, ValueError):
            continue
        params = set(sig.parameters)
        leaked = forbidden & params
        assert not leaked, (
            f"registry.{name} accepts immutable snapshot field(s): {leaked}"
        )


def test_open_position_dataclass_is_frozen():
    """A stale watcher tick mutating a position dict must not bleed forward.
    The dataclass freeze is the structural guarantee.
    """
    p = _make_position()
    with pytest.raises(Exception):
        p.applied_tp_pct = 0.99  # type: ignore[misc]


def test_open_position_to_router_dict_does_not_carry_applied_fields():
    """``to_router_dict`` is what crosses into the close engine — it must
    NOT carry applied_* into the close path. The engine never needs them
    and exposing them invites accidental mutation downstream.
    """
    p = _make_position()
    payload = p.to_router_dict()
    assert "applied_tp_pct" not in payload
    assert "applied_sl_pct" not in payload


def test_evaluate_does_not_mutate_position():
    """Pure decision: position fields must be unchanged after evaluate."""
    p = _make_position(yes_price=0.50, applied_tp_pct=0.20)
    snapshot = (
        p.applied_tp_pct, p.applied_sl_pct, p.force_close_intent,
        p.close_failure_count,
    )
    _run(exit_watcher.evaluate(p))
    assert (
        p.applied_tp_pct, p.applied_sl_pct, p.force_close_intent,
        p.close_failure_count,
    ) == snapshot


# ---------------------------------------------------------------------------
# MARKET_EXPIRED: Phase A (None-price retry) and Phase B (resolved markets).
# ---------------------------------------------------------------------------

def test_run_once_none_price_after_retry_closes_as_expired():
    """Phase A: _fetch_live_price returns None for _EXPIRED_TICK_THRESHOLD ticks → MARKET_EXPIRED.

    The per-position counter is pre-seeded to _EXPIRED_TICK_THRESHOLD - 1 so that
    a single run_once() call (2 fetch attempts within that tick) crosses the threshold
    and closes the position. This matches the 3-tick / ~90s guard added by P1-A.
    """
    captured_expired: list[dict] = []

    async def _mock_expired_alert(**kw):
        captured_expired.append(kw)

    pos = _make_position(yes_price=0.40)
    close_expired = AsyncMock(return_value=True)
    list_open = AsyncMock(return_value=[pos])
    list_open_resolved = AsyncMock(return_value=[])
    fetch_none = AsyncMock(return_value=None)

    patches = [
        patch.object(registry, "list_open_for_exit", list_open),
        patch.object(registry, "list_open_on_resolved_markets", list_open_resolved),
        patch.object(registry, "close_as_expired", close_expired),
        patch.object(exit_watcher, "_fetch_live_price", fetch_none),
        # Pre-seed counter to threshold - 1 so this tick crosses the threshold.
        patch.dict(exit_watcher._price_fail_counts,
                   {pos.id: exit_watcher._EXPIRED_TICK_THRESHOLD - 1}),
        # Market IS actually resolved — guard passes and close proceeds.
        patch.object(exit_watcher, "_market_actually_expired", AsyncMock(return_value=True)),
        _patch_audit_noop(),
        patch.object(monitoring_alerts, "alert_user_market_expired", _mock_expired_alert),
    ]
    for p_ in patches:
        p_.start()
    try:
        result = _run(exit_watcher.run_once())
    finally:
        for p_ in patches:
            p_.stop()

    assert result.expired == 1
    assert result.submitted == 0
    assert result.held == 0
    # Two fetch attempts within this tick: initial + one retry before declaring expired.
    assert fetch_none.await_count == 2
    close_expired.assert_awaited_once_with(pos.id, pos.user_id, pos.size_usdc)
    # User alert suppressed — exit_watcher logs to logger.info instead.
    assert len(captured_expired) == 0


def test_run_once_market_expired_on_resolved_market():
    """Phase B: open position on resolved market → closed as MARKET_EXPIRED directly."""
    captured_expired: list[dict] = []

    async def _mock_expired_alert(**kw):
        captured_expired.append(kw)

    pos = _make_position(market_resolved=True)
    close_expired = AsyncMock(return_value=True)
    list_open = AsyncMock(return_value=[])
    list_open_resolved = AsyncMock(return_value=[pos])

    patches = [
        patch.object(registry, "list_open_for_exit", list_open),
        patch.object(registry, "list_open_on_resolved_markets", list_open_resolved),
        patch.object(registry, "close_as_expired", close_expired),
        _patch_audit_noop(),
        patch.object(monitoring_alerts, "alert_user_market_expired", _mock_expired_alert),
    ]
    for p_ in patches:
        p_.start()
    try:
        result = _run(exit_watcher.run_once())
    finally:
        for p_ in patches:
            p_.stop()

    assert result.expired == 1
    assert result.submitted == 0
    close_expired.assert_awaited_once_with(pos.id, pos.user_id, pos.size_usdc)
    # User alert suppressed — exit_watcher logs to logger.info instead.
    assert len(captured_expired) == 0


# ---------------------------------------------------------------------------
# _market_actually_expired guard tests (runtime-autotrade-fix)
# ---------------------------------------------------------------------------


def _make_pool_for_market(*, resolved: bool, resolution_at=None):
    """Return a fake asyncpg pool returning a market row with given resolved/end_date."""
    from unittest.mock import MagicMock
    row = {"resolved": resolved, "resolution_at": resolution_at}
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=row)
    pool = MagicMock()
    acq = MagicMock()
    acq.__aenter__ = AsyncMock(return_value=conn)
    acq.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=acq)
    return pool


def test_none_price_on_unresolved_market_does_not_close():
    """Phase A: 3 None ticks, DB resolved=False → position stays open, no close call."""
    pos = _make_position()
    fetch_none = AsyncMock(return_value=None)
    close_expired = AsyncMock(return_value=True)
    list_open = AsyncMock(return_value=[pos])
    list_open_resolved = AsyncMock(return_value=[])
    pool = _make_pool_for_market(resolved=False)

    patches = [
        patch.object(registry, "list_open_for_exit", list_open),
        patch.object(registry, "list_open_on_resolved_markets", list_open_resolved),
        patch.object(registry, "close_as_expired", close_expired),
        patch.object(exit_watcher, "_fetch_live_price", fetch_none),
        # Pre-seed counter to threshold - 1 so this tick crosses the threshold.
        patch.dict(exit_watcher._price_fail_counts,
                   {pos.id: exit_watcher._EXPIRED_TICK_THRESHOLD - 1}),
        patch.object(exit_watcher, "get_pool", return_value=pool),
        _patch_audit_noop(),
    ]
    for p_ in patches:
        p_.start()
    try:
        result = _run(exit_watcher.run_once())
        # Counter pinned at threshold, not grown beyond it (checked inside patch scope).
        assert exit_watcher._price_fail_counts.get(pos.id) == exit_watcher._EXPIRED_TICK_THRESHOLD
    finally:
        for p_ in patches:
            p_.stop()

    assert result.expired == 0, "Must not close when market is still live"
    close_expired.assert_not_awaited()


def test_none_price_on_resolved_market_closes():
    """Phase A: 3 None ticks, DB resolved=True → position closes as market_expired."""
    pos = _make_position()
    fetch_none = AsyncMock(return_value=None)
    close_expired = AsyncMock(return_value=True)
    list_open = AsyncMock(return_value=[pos])
    list_open_resolved = AsyncMock(return_value=[])
    pool = _make_pool_for_market(resolved=True)

    patches = [
        patch.object(registry, "list_open_for_exit", list_open),
        patch.object(registry, "list_open_on_resolved_markets", list_open_resolved),
        patch.object(registry, "close_as_expired", close_expired),
        patch.object(exit_watcher, "_fetch_live_price", fetch_none),
        patch.dict(exit_watcher._price_fail_counts,
                   {pos.id: exit_watcher._EXPIRED_TICK_THRESHOLD - 1}),
        patch.object(exit_watcher, "get_pool", return_value=pool),
        _patch_audit_noop(),
    ]
    for p_ in patches:
        p_.start()
    try:
        result = _run(exit_watcher.run_once())
    finally:
        for p_ in patches:
            p_.stop()

    assert result.expired == 1
    close_expired.assert_awaited_once()


def test_none_price_on_past_end_date_closes():
    """Phase A: 3 None ticks, resolved=False but resolution_at in the past → closes."""
    from datetime import datetime, timedelta, timezone as tz
    past = datetime.now(tz.utc) - timedelta(days=1)

    pos = _make_position()
    fetch_none = AsyncMock(return_value=None)
    close_expired = AsyncMock(return_value=True)
    list_open = AsyncMock(return_value=[pos])
    list_open_resolved = AsyncMock(return_value=[])
    pool = _make_pool_for_market(resolved=False, resolution_at=past)

    patches = [
        patch.object(registry, "list_open_for_exit", list_open),
        patch.object(registry, "list_open_on_resolved_markets", list_open_resolved),
        patch.object(registry, "close_as_expired", close_expired),
        patch.object(exit_watcher, "_fetch_live_price", fetch_none),
        patch.dict(exit_watcher._price_fail_counts,
                   {pos.id: exit_watcher._EXPIRED_TICK_THRESHOLD - 1}),
        patch.object(exit_watcher, "get_pool", return_value=pool),
        _patch_audit_noop(),
    ]
    for p_ in patches:
        p_.start()
    try:
        result = _run(exit_watcher.run_once())
    finally:
        for p_ in patches:
            p_.stop()

    assert result.expired == 1
    close_expired.assert_awaited_once()
