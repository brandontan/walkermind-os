"""WARP-53 — Telegram delivery hardening + paper close idempotency proof.

Issue #1252. Tier STANDARD, Claim NARROW INTEGRATION.

Hermetic — no real Telegram, no real Postgres, no real network. Every
external surface is patched at the import seam.

Coverage:
  1. notifications.send: 429 RetryAfter is honoured (wait = retry_after,
     capped at 30s) rather than the exponential backoff that used to ignore
     Telegram's recommended pause.
  2. notifications.send: returns False after attempt budget exhausted by
     repeated 429s and logs a permanent-failure ERROR (no silent swallow).
  3. trade_notifications.notifier._send: when notifications.send returns
     False, a notifier-level WARNING with event + market_id context is
     emitted so the dropped trade-lifecycle event is auditable per-event.
  4. services.notification_service._send_safe: same per-event WARNING
     contract for the auto-trade / copy-trade / blocked-trade receipts.
  5. monitoring.alerts.alert_user_tp_hit: dropped exit-receipt surfaces a
     WARNING tagged with alert_kind + telegram_user_id + market_id.
  6. paper.close_position: two concurrent calls on the same position
     produce exactly one ledger entry and exactly one snapshot — the
     second call returns ``exit_reason='already_closed'`` (idempotency
     guard at the DB UPDATE level is the single source of truth).
"""
from __future__ import annotations

import asyncio
import logging
import time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from telegram.error import RetryAfter

from projects.polymarket.crusaderbot import notifications
from projects.polymarket.crusaderbot.domain.execution import paper as paper_exec
from projects.polymarket.crusaderbot.monitoring import alerts as monitoring_alerts
from projects.polymarket.crusaderbot.services import notification_service
from projects.polymarket.crusaderbot.services.trade_notifications import notifier as notifier_mod
from projects.polymarket.crusaderbot.services.trade_notifications import TradeNotifier


# ---------------------------------------------------------------------------
# notifications.send — RetryAfter is honoured on 429
# ---------------------------------------------------------------------------


def _run(coro):
    return asyncio.run(coro)


def test_send_honours_retry_after_on_429(monkeypatch):
    """First call raises RetryAfter(retry_after=2); second call succeeds.

    The wait between attempts must be >= 2.0 seconds (Telegram's mandated
    pause) — never sub-second exponential backoff that ignored the server
    hint and burned the attempt budget at <1s intervals.
    """
    waits: list[float] = []
    real_sleep = asyncio.sleep

    async def _record_sleep(seconds: float) -> None:
        waits.append(seconds)
        # Don't actually sleep — keep the test fast.
        await real_sleep(0)

    monkeypatch.setattr("tenacity.asyncio.sleep", _record_sleep, raising=False)
    monkeypatch.setattr("asyncio.sleep", _record_sleep)

    call_count = {"n": 0}

    async def _send_message(**_kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RetryAfter(retry_after=2)
        return MagicMock()

    fake_bot = MagicMock()
    fake_bot.send_message = AsyncMock(side_effect=_send_message)

    with patch.object(notifications, "get_bot", return_value=fake_bot):
        ok = _run(notifications.send(123, "hello"))

    assert ok is True
    assert call_count["n"] == 2
    # tenacity records every sleep including the retry; the first non-zero
    # wait must be >= 2.0 (Telegram's retry_after) rather than the previous
    # wait_exponential(min=1) which produced ~1.0s and ignored the server hint.
    assert any(w >= 2.0 for w in waits), (
        f"Expected wait >= 2.0s honouring RetryAfter, got waits={waits!r}"
    )


def test_send_caps_retry_after_at_30_seconds(monkeypatch):
    """If Telegram returns RetryAfter(retry_after=600), we cap at 30s so a
    single send cannot block the caller for ten minutes. After the capped
    wait the retry runs and must still succeed.
    """
    waits: list[float] = []
    real_sleep = asyncio.sleep

    async def _record_sleep(seconds: float) -> None:
        waits.append(seconds)
        await real_sleep(0)

    monkeypatch.setattr("tenacity.asyncio.sleep", _record_sleep, raising=False)
    monkeypatch.setattr("asyncio.sleep", _record_sleep)

    call_count = {"n": 0}

    async def _send_message(**_kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RetryAfter(retry_after=600)
        return MagicMock()

    fake_bot = MagicMock()
    fake_bot.send_message = AsyncMock(side_effect=_send_message)

    with patch.object(notifications, "get_bot", return_value=fake_bot):
        ok = _run(notifications.send(123, "hello"))

    assert ok is True
    # No single sleep above the 30s cap.
    assert all(w <= 30.0 for w in waits), (
        f"Expected all waits <= 30s cap, got waits={waits!r}"
    )


def test_send_returns_false_after_attempt_budget_exhausted(monkeypatch, caplog):
    """4 consecutive RetryAfter exceptions exhaust the attempt budget;
    notifications.send returns False (never raises) and logs at ERROR.
    """
    async def _fast_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("tenacity.asyncio.sleep", _fast_sleep, raising=False)
    monkeypatch.setattr("asyncio.sleep", _fast_sleep)

    fake_bot = MagicMock()
    fake_bot.send_message = AsyncMock(side_effect=RetryAfter(retry_after=1))

    with patch.object(notifications, "get_bot", return_value=fake_bot):
        with caplog.at_level(logging.ERROR, logger=notifications.logger.name):
            ok = _run(notifications.send(123, "hello"))

    assert ok is False
    assert fake_bot.send_message.await_count == notifications._MAX_SEND_ATTEMPTS
    # ERROR record present — no silent swallow.
    assert any(
        "Telegram send permanently failed" in r.getMessage()
        for r in caplog.records
    ), [r.getMessage() for r in caplog.records]


# ---------------------------------------------------------------------------
# trade_notifications.notifier._send — bool return surfaces per-event WARNING
# ---------------------------------------------------------------------------


def test_notifier_logs_warning_when_send_returns_false(caplog):
    """A False return from notifications.send must produce a notifier-level
    WARNING tagged with notification_event + market_id so the dropped trade
    receipt is auditable in logs.
    """
    notifier = TradeNotifier()

    fake_send = AsyncMock(return_value=False)
    enabled_gate = AsyncMock(return_value=True)

    with patch.object(notifier_mod.notifications, "send", fake_send), \
         patch(
             "projects.polymarket.crusaderbot.users.notifications_enabled_by_telegram_id",
             enabled_gate,
         ), \
         caplog.at_level(logging.WARNING, logger=notifier_mod.__name__):
        _run(notifier.notify_tp_hit(
            telegram_user_id=4242,
            market_id="mkt-abc",
            market_question="Will X happen?",
            side="yes",
            exit_price=0.55,
            pnl_usdc=12.34,
        ))

    fake_send.assert_awaited_once()
    drop_records = [
        r for r in caplog.records
        if "trade_notification.delivery_dropped" in r.getMessage()
    ]
    assert drop_records, (
        "Expected delivery_dropped WARNING; got "
        f"{[r.getMessage() for r in caplog.records]!r}"
    )
    msg = drop_records[0].getMessage()
    assert "tp_hit" in msg
    assert "mkt-abc" in msg
    assert "4242" in msg


# ---------------------------------------------------------------------------
# notification_service._send_safe — bool return surfaces per-event WARNING
# ---------------------------------------------------------------------------


def test_notification_service_logs_warning_when_send_returns_false(caplog):
    fake_send = AsyncMock(return_value=False)
    enabled_gate = AsyncMock(return_value=True)

    with patch.object(notification_service.notifications, "send", fake_send), \
         patch.object(
             notification_service, "notifications_enabled_by_telegram_id",
             enabled_gate,
         ), \
         caplog.at_level(logging.WARNING, logger=notification_service.logger.name):
        _run(notification_service._send_safe(
            telegram_user_id=5151,
            text="receipt",
            event_name="position.opened",
        ))

    fake_send.assert_awaited_once()
    drop_records = [
        r for r in caplog.records
        if "notification_service: delivery_dropped" in r.getMessage()
    ]
    assert drop_records, (
        "Expected delivery_dropped WARNING; got "
        f"{[r.getMessage() for r in caplog.records]!r}"
    )
    msg = drop_records[0].getMessage()
    assert "position.opened" in msg
    assert "5151" in msg


# ---------------------------------------------------------------------------
# monitoring.alerts.alert_user_tp_hit — bool return surfaces tagged WARNING
# ---------------------------------------------------------------------------


def test_alert_user_tp_hit_logs_warning_when_dropped(caplog):
    fake_send = AsyncMock(return_value=False)

    with patch.object(monitoring_alerts.notifications, "send", fake_send), \
         caplog.at_level(logging.WARNING, logger=monitoring_alerts.logger.name):
        _run(monitoring_alerts.alert_user_tp_hit(
            telegram_user_id=9999,
            market_id="mkt-xyz",
            market_question="Resolves yes?",
            side="yes",
            exit_price=0.62,
            pnl_usdc=8.0,
            mode="paper",
        ))

    fake_send.assert_awaited_once()
    drop_records = [
        r for r in caplog.records
        if "alert_user.delivery_dropped" in r.getMessage()
    ]
    assert drop_records, [r.getMessage() for r in caplog.records]
    msg = drop_records[0].getMessage()
    assert "tp_hit" in msg
    assert "9999" in msg
    assert "mkt-xyz" in msg


# ---------------------------------------------------------------------------
# paper.close_position — double-close idempotency proof
# ---------------------------------------------------------------------------


def test_paper_close_position_idempotent_under_double_close():
    """Second call against the same position returns ``already_closed`` and
    fires neither the ledger credit nor the snapshot writer. The DB-level
    guard (``WHERE status='open'``) is the single source of truth — this
    test pins the Python-side behaviour against accidental regressions.
    """
    pos_id = uuid4()
    user_id = uuid4()
    position = {
        "id": pos_id,
        "user_id": user_id,
        "size_usdc": Decimal("100"),
        "entry_price": 0.40,
        "side": "yes",
    }

    # First close: UPDATE matched the open row -> fetchval returns pos_id.
    # Second close: UPDATE matched zero rows -> fetchval returns None.
    fetchval_results = [pos_id, None]

    async def _fetchval(*_a, **_k):
        return fetchval_results.pop(0)

    ledger_execute_count = {"n": 0}

    async def _execute(*_a, **_k):
        # ledger INSERT + wallets UPDATE both come through conn.execute;
        # count total calls to prove the second close does not write.
        ledger_execute_count["n"] += 1
        return None

    conn = MagicMock()
    conn.fetchval = AsyncMock(side_effect=_fetchval)
    conn.fetchrow = AsyncMock(return_value=None)
    conn.execute = AsyncMock(side_effect=_execute)
    txn = MagicMock()
    txn.__aenter__ = AsyncMock(return_value=None)
    txn.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=txn)
    pool = MagicMock()
    acq = MagicMock()
    acq.__aenter__ = AsyncMock(return_value=conn)
    acq.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=acq)

    snapshot_mock = AsyncMock(return_value=uuid4())
    audit_mock = AsyncMock(return_value=None)

    with patch.object(paper_exec, "get_pool", return_value=pool), \
         patch.object(paper_exec.portfolio_snapshots, "write_snapshot", snapshot_mock), \
         patch.object(paper_exec.audit, "write", audit_mock):
        first = _run(paper_exec.close_position(
            position=position, exit_price=0.50, exit_reason="tp_hit",
        ))
        executes_after_first = ledger_execute_count["n"]
        second = _run(paper_exec.close_position(
            position=position, exit_price=0.50, exit_reason="tp_hit",
        ))

    assert first["exit_reason"] == "tp_hit"
    assert second["exit_reason"] == "already_closed"
    # Snapshot writer fired exactly once — never on the no-op re-close.
    assert snapshot_mock.await_count == 1
    # Audit writer fired exactly once — never on the no-op re-close.
    assert audit_mock.await_count == 1
    # Ledger writes (conn.execute) only happened during the first close —
    # no additional ledger writes on the idempotent second call. ledger
    # credit emits 2 executes (INSERT into ledger + UPDATE wallets); zero
    # additional executes after the first close confirms idempotency.
    assert ledger_execute_count["n"] == executes_after_first
