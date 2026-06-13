"""Behaviour pins for #1810 — live-mode-paper-trade-contamination-blocker.

Production bug: a user switched PAPER -> LIVE, yet Telegram still emitted an
active ``[PAPER] Strategy exit`` for an Ethereum candle position. Root cause: a
paper position still ``status='open'`` at switch time is closed by the exit
watcher (the 30s ``exit_watch`` loop or the 5s candle fast loop) in a race with
``enable_live_self_serve``'s archival UPDATE. The watcher derived the alert mode
from the STALE ``position.mode`` row, so it surfaced active paper automation
AFTER the user was already LIVE.

These tests prove the fix end-to-end at the worker boundary (no DB, no broker,
no Telegram):

1. ``paper_event_contaminates_live`` predicate truth table.
2. ``get_active_trading_mode`` reads the authoritative
   ``user_settings.trading_mode`` and defaults to PAPER.
3. exit_watcher suppresses the user alert AND the ``position.closed`` event when
   the owning user is now LIVE (the close still persists — silent paper cleanup).
4. Control: a still-PAPER user's paper exit DOES notify (no regression).
5. Per-user isolation: one user's LIVE switch never suppresses another user's
   paper exit notification.
6. No real order / fund movement and no live-guard flips are involved.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest

from projects.polymarket.crusaderbot.domain.activation import live_mode
from projects.polymarket.crusaderbot.domain.execution import exit_watcher
from projects.polymarket.crusaderbot.domain.positions.registry import (
    ExitReason,
    OpenPositionForExit,
)
from projects.polymarket.crusaderbot.monitoring import alerts as monitoring_alerts


def _run(coro):
    return asyncio.run(coro)


def _paper_position(
    *,
    user_id: UUID | None = None,
    mode: str = "paper",
    market_id: str = "MKT-ETH-825",
    market_question: str = "Ethereum Up or Down - June 12, 8:25PM-8:30PM ET",
) -> OpenPositionForExit:
    """An open candle paper position priced flat to entry so TP/SL never trip —
    the strategy-exit hook (priority 4) decides the close in evaluate()."""
    return OpenPositionForExit(
        id=uuid4(),
        user_id=user_id or uuid4(),
        telegram_user_id=12345,
        market_id=market_id,
        market_question=market_question,
        side="yes",
        entry_price=0.10,
        size_usdc=0.25,
        mode=mode,
        status="open",
        applied_tp_pct=0.20,
        applied_sl_pct=0.10,
        force_close_intent=False,
        close_failure_count=0,
        yes_price=0.065,
        no_price=0.935,
        market_resolved=False,
        resolution_at=datetime.now(timezone.utc),
        risk_profile="balanced",
    )


# ---------------------------------------------------------------------------
# 1. Predicate truth table — pure, no IO.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "event_mode,active_mode,expected",
    [
        ("paper", "live", True),            # the production contamination case
        ("paper_archived", "live", True),   # archived cleanup surfacing post-switch
        ("PAPER", "LIVE", True),            # case-insensitive
        ("paper", "paper", False),          # normal paper trading — never suppress
        ("live", "live", False),            # genuine live exit — never suppress
        ("live", "paper", False),           # live event while paper (no contamination)
        ("paper_archived", "paper", False), # archived row but user still paper
    ],
)
def test_paper_event_contaminates_live_truth_table(event_mode, active_mode, expected):
    assert (
        live_mode.paper_event_contaminates_live(
            event_mode=event_mode, active_mode=active_mode
        )
        is expected
    )


def test_paper_event_contaminates_live_handles_none():
    # None defaults to paper on both sides -> not contamination.
    assert live_mode.paper_event_contaminates_live(
        event_mode=None, active_mode=None
    ) is False
    # None event mode (defaults paper) while user is live -> contamination.
    assert live_mode.paper_event_contaminates_live(
        event_mode=None, active_mode="live"
    ) is True


# ---------------------------------------------------------------------------
# 2. Authoritative current-mode read.
# ---------------------------------------------------------------------------

class _FakeConn:
    def __init__(self, value: Any):
        self._value = value
        self.sql: str | None = None

    async def fetchval(self, sql: str, *args):
        self.sql = sql
        return self._value


def test_get_active_trading_mode_reads_user_settings():
    conn = _FakeConn("live")
    mode = _run(live_mode.get_active_trading_mode(uuid4(), conn))
    assert mode == "live"
    # Authoritative single source of truth — the same column WebTrader/Telegram read.
    assert "trading_mode FROM user_settings" in (conn.sql or "")


def test_get_active_trading_mode_defaults_to_paper_when_missing():
    conn = _FakeConn(None)
    assert _run(live_mode.get_active_trading_mode(uuid4(), conn)) == "paper"


# ---------------------------------------------------------------------------
# Behaviour harness for exit_watcher.run_once.
# ---------------------------------------------------------------------------

class _Captured:
    def __init__(self) -> None:
        self.strategy_exit: list[dict] = []
        self.closed_submits: list[dict] = []
        self.events: list[tuple] = []
        self.audit_actions: list[str] = []


def _exit_watcher_patches(captured: _Captured, *, active_mode_by_user: dict[UUID, str]):
    async def _strat(**kw):
        captured.strategy_exit.append(kw)

    async def _emit(event_name, **kw):
        captured.events.append((event_name, kw))

    async def _audit(**kw):
        captured.audit_actions.append(kw.get("action", ""))

    async def _fetch_price(market_id: str, side: str, *, token_id=None):
        return 0.10  # flat to entry: TP/SL never trip, so the strategy hook decides

    async def _active_mode(user_id, conn=None):
        return active_mode_by_user.get(user_id, "paper")

    return [
        patch.object(monitoring_alerts, "alert_user_strategy_exit", _strat),
        patch.object(exit_watcher, "_fetch_live_price", _fetch_price),
        patch(
            "projects.polymarket.crusaderbot.domain.execution.exit_watcher.audit.write",
            new=_audit,
        ),
        patch(
            "projects.polymarket.crusaderbot.core.event_bus.emit",
            new=_emit,
        ),
        patch.object(live_mode, "get_active_trading_mode", _active_mode),
    ]


async def _strategy_always_exit(position, current_price) -> bool:
    return True


def _run_watcher(positions, captured, *, active_mode_by_user):
    async def _submitter(*, position, exit_price, exit_reason):
        captured.closed_submits.append(
            {"id": position["id"], "reason": exit_reason, "price": exit_price}
        )
        return {"pnl_usdc": -0.09, "exit_price": exit_price, "exit_reason": exit_reason}

    async def _loader():
        return list(positions)

    patches = _exit_watcher_patches(captured, active_mode_by_user=active_mode_by_user)
    for p_ in patches:
        p_.start()
    try:
        return _run(
            exit_watcher.run_once(
                strategy_evaluator=_strategy_always_exit,
                close_submitter=_submitter,
                position_loader=_loader,
                run_resolved_phase=False,
            )
        )
    finally:
        for p_ in patches:
            p_.stop()


# ---------------------------------------------------------------------------
# 3. Contamination: paper position, user now LIVE -> suppress alert + event.
# ---------------------------------------------------------------------------

def test_paper_exit_suppressed_when_user_now_live():
    captured = _Captured()
    pos = _paper_position(mode="paper")

    result = _run_watcher(
        [pos], captured, active_mode_by_user={pos.user_id: "live"}
    )

    # The close still happened (silent historical paper cleanup) ...
    assert result.submitted == 1
    assert len(captured.closed_submits) == 1
    assert captured.closed_submits[0]["reason"] == ExitReason.STRATEGY_EXIT.value
    # ... but NO active [PAPER] Strategy exit notification fired ...
    assert captured.strategy_exit == []
    # ... and NO position.closed event was emitted (covers Telegram + WebTrader).
    assert all(name != "position.closed" for name, _ in captured.events)
    # A diagnostic suppression audit is recorded for operator traceability.
    assert "exit_watcher_paper_exit_suppressed_post_live" in captured.audit_actions


# ---------------------------------------------------------------------------
# 4. Control: paper position, user still PAPER -> notify as normal.
# ---------------------------------------------------------------------------

def test_paper_exit_still_notifies_when_user_still_paper():
    captured = _Captured()
    pos = _paper_position(mode="paper")

    result = _run_watcher(
        [pos], captured, active_mode_by_user={pos.user_id: "paper"}
    )

    assert result.submitted == 1
    # Normal paper trading: the strategy-exit alert fires with paper mode.
    assert len(captured.strategy_exit) == 1
    assert captured.strategy_exit[0]["mode"] == "paper"
    # position.closed event emitted for the SSE/notification bridges.
    assert any(name == "position.closed" for name, _ in captured.events)
    assert "exit_watcher_paper_exit_suppressed_post_live" not in captured.audit_actions


# ---------------------------------------------------------------------------
# 5. Per-user isolation — one user's LIVE switch never silences another's paper.
# ---------------------------------------------------------------------------

def test_live_switch_does_not_suppress_other_users_paper_exit():
    captured = _Captured()
    user_live = uuid4()
    user_paper = uuid4()
    pos_live_user = _paper_position(user_id=user_live, market_id="MKT-A")
    pos_paper_user = _paper_position(user_id=user_paper, market_id="MKT-B")

    result = _run_watcher(
        [pos_live_user, pos_paper_user],
        captured,
        active_mode_by_user={user_live: "live", user_paper: "paper"},
    )

    # Both positions are closed by the watcher ...
    assert result.submitted == 2
    # ... but exactly ONE alert fires — the still-paper user's. The user who
    # switched to LIVE is suppressed; the other user is untouched.
    assert len(captured.strategy_exit) == 1
    fired = captured.strategy_exit[0]
    assert fired["market_id"] == "MKT-B"
    assert fired["mode"] == "paper"
    assert captured.audit_actions.count(
        "exit_watcher_paper_exit_suppressed_post_live"
    ) == 1


# ---------------------------------------------------------------------------
# 6. Live exit for a LIVE user is never suppressed by the guard.
# ---------------------------------------------------------------------------

def test_live_exit_not_suppressed_for_live_user():
    captured = _Captured()
    pos = _paper_position(mode="live")  # a genuine live position

    result = _run_watcher(
        [pos], captured, active_mode_by_user={pos.user_id: "live"}
    )

    assert result.submitted == 1
    # live event + live mode -> not contamination -> alert fires with live mode.
    assert len(captured.strategy_exit) == 1
    assert captured.strategy_exit[0]["mode"] == "live"
    assert "exit_watcher_paper_exit_suppressed_post_live" not in captured.audit_actions
