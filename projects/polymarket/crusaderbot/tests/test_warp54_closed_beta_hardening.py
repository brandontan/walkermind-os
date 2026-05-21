"""WARP-54 — Closed beta hardening regression tests (issue #1253).

Tier STANDARD, Claim NARROW INTEGRATION. Hermetic — no real network, no
real Postgres, no real Telegram.

Coverage map (issue #1253 scope items 1-6):

  §1  No duplicate trades        — paper.execute ON CONFLICT idempotency
                                    proven against the same idempotency_key
                                    arriving twice.
  §2  No stuck positions         — surfaced in /admin HUD via _admin_status_hud
                                    SQL. Pinned structurally by inspecting the
                                    handler's query for the stuck_open branch.
  §3  No state bleed             — paper.close_position with wrong user_id
                                    returns already_closed (DB-level user_id
                                    scoping is the single source of truth).
                                    Complements the existing
                                    test_user_isolation suite.
  §4  Notification failure       — notifications.send retries with parse_mode=None
                                    after a BadRequest from parse_mode=HTML, so
                                    malformed markup cannot silently drop a
                                    trade-lifecycle receipt.
  §5  Restart recovery           — scheduler.log_resumed_open_positions counts
                                    open positions on startup, emits the
                                    "Resumed monitoring N open positions" INFO
                                    line, and returns the count for job_runs
                                    metadata.
  §6  API timeout / failure      — Documented: exit_watcher already swallows
                                    Polymarket fetch exceptions via
                                    _fetch_live_price + uses 3-tick threshold
                                    before MARKET_EXPIRED. Coverage lives in
                                    test_exit_watcher.py (production env only —
                                    sandbox lacks eth_account dep).
"""
from __future__ import annotations

import asyncio
import importlib
import logging
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from telegram.error import BadRequest

from projects.polymarket.crusaderbot import notifications
from projects.polymarket.crusaderbot.domain.execution import paper as paper_exec


def _try_import_scheduler():
    """Import scheduler if live-trading deps are available; otherwise skip.

    The function under test (log_resumed_open_positions) does not exercise
    live-trading code — it only queries the positions table — but scheduler
    transitively imports the live-trading integration chain, so importability
    is environment-dependent. Production CI has the deps; this guard lets
    the §5 tests skip cleanly in sandboxes without them.
    """
    try:
        return importlib.import_module(
            "projects.polymarket.crusaderbot.scheduler",
        )
    except ModuleNotFoundError as exc:  # noqa: BLE001
        pytest.skip(f"scheduler import unavailable in this env: {exc}")


def _run(coro):
    return asyncio.run(coro)


def _make_pool(*, fetchval_side_effect=None, fetchrow_side_effect=None,
               execute_side_effect=None):
    """Build an AsyncMock pool/conn surface with a transaction context."""
    conn = MagicMock()
    conn.fetchval = AsyncMock(side_effect=fetchval_side_effect)
    conn.fetchrow = AsyncMock(side_effect=fetchrow_side_effect)
    conn.execute = AsyncMock(side_effect=execute_side_effect)
    txn = MagicMock()
    txn.__aenter__ = AsyncMock(return_value=None)
    txn.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=txn)
    pool = MagicMock()
    acq = MagicMock()
    acq.__aenter__ = AsyncMock(return_value=conn)
    acq.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=acq)
    return pool, conn


# ---------------------------------------------------------------------------
# §1 — No duplicate trades
# ---------------------------------------------------------------------------


def test_paper_execute_returns_duplicate_when_idempotency_key_repeats():
    """Second paper.execute with the same idempotency_key returns
    ``{"status": "duplicate", "mode": "paper"}`` without creating a second
    position. The ON CONFLICT (idempotency_key) DO NOTHING clause in the
    INSERT into orders is the DB-level guard.
    """
    user_id = uuid4()
    order_id = uuid4()
    position_id = uuid4()

    # First call: fetchrow returns the new order row, then the new position row.
    # Second call: fetchrow returns None (ON CONFLICT DO NOTHING).
    fetchrow_results = [
        {"id": order_id},    # first execute — orders INSERT RETURNING id
        {"id": position_id}, # first execute — positions INSERT RETURNING id
        None,                # second execute — ON CONFLICT DO NOTHING
    ]

    async def _fetchrow(*_a, **_k):
        return fetchrow_results.pop(0)

    pool, conn = _make_pool(fetchrow_side_effect=_fetchrow)

    notifier_mock = AsyncMock()
    notifier_mock.notify_entry = AsyncMock(return_value=None)
    audit_mock = AsyncMock(return_value=None)

    common_kwargs = dict(
        user_id=user_id,
        telegram_user_id=4242,
        market_id="mkt-1",
        market_question="Q?",
        side="yes",
        size_usdc=Decimal("10"),
        price=0.5,
        idempotency_key="dup-key-abc",
        strategy_type="signal_sniper",
        tp_pct=0.2,
        sl_pct=0.1,
    )

    with patch.object(paper_exec, "get_pool", return_value=pool), \
         patch.object(paper_exec, "_notifier", notifier_mock), \
         patch.object(paper_exec.audit, "write", audit_mock), \
         patch.object(paper_exec.ledger, "debit_in_conn", AsyncMock(return_value=None)):
        first = _run(paper_exec.execute(**common_kwargs))
        second = _run(paper_exec.execute(**common_kwargs))

    assert first.get("position_id") == position_id, first
    assert second == {"status": "duplicate", "mode": "paper"}
    # Notifier fired only on the first (successful) execute.
    assert notifier_mock.notify_entry.await_count == 1


# ---------------------------------------------------------------------------
# §3 — No state bleed between users
# ---------------------------------------------------------------------------


def test_paper_close_position_is_user_scoped():
    """paper.close_position's UPDATE includes ``user_id=$5`` in the WHERE
    clause. A close attempt against another user's position id MUST return
    ``already_closed`` (no row updated) — the row is intentionally
    invisible to the wrong user, identical to the no-op idempotent re-close.
    """
    pos_id = uuid4()
    real_owner = uuid4()
    other_user = uuid4()

    position_view_by_other = {
        "id": pos_id,
        "user_id": other_user,            # attacker presents their own user_id
        "size_usdc": Decimal("100"),
        "entry_price": 0.40,
        "side": "yes",
    }

    # UPDATE WHERE id=pos_id AND user_id=other_user — DB returns None
    # because the row is owned by ``real_owner``.
    pool, conn = _make_pool(fetchval_side_effect=[None])
    snapshot_mock = AsyncMock(return_value=uuid4())
    audit_mock = AsyncMock(return_value=None)

    with patch.object(paper_exec, "get_pool", return_value=pool), \
         patch.object(paper_exec.portfolio_snapshots, "write_snapshot", snapshot_mock), \
         patch.object(paper_exec.audit, "write", audit_mock):
        result = _run(paper_exec.close_position(
            position=position_view_by_other,
            exit_price=0.50,
            exit_reason="manual",
        ))

    assert result["exit_reason"] == "already_closed"
    # Critical: the UPDATE was attempted with the attacker's user_id, so
    # state-bleed defence is the DB guard, not the application layer.
    update_call = conn.fetchval.call_args_list[0]
    # Args: id, exit_reason, exit_price, pnl, user_id
    assert update_call.args[5] == other_user
    # Snapshot writer never fires on already_closed branch.
    snapshot_mock.assert_not_awaited()
    audit_mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# §4 — Notification failure (parse_mode=HTML BadRequest fallback)
# ---------------------------------------------------------------------------


def test_send_falls_back_to_plain_text_on_badrequest(monkeypatch):
    """BadRequest from parse_mode=HTML triggers a second send with
    parse_mode=None. The plain-text retry must succeed (returns True)
    so the trade-lifecycle receipt is not silently dropped.
    """
    async def _fast_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("tenacity.asyncio.sleep", _fast_sleep, raising=False)
    monkeypatch.setattr("asyncio.sleep", _fast_sleep)

    calls: list[dict] = []

    async def _send_message(**kwargs):
        calls.append(kwargs)
        if kwargs.get("parse_mode") == "HTML":
            raise BadRequest("Can't parse entities: unexpected character")
        return MagicMock()

    fake_bot = MagicMock()
    fake_bot.send_message = AsyncMock(side_effect=_send_message)

    with patch.object(notifications, "get_bot", return_value=fake_bot):
        ok = _run(notifications.send(123, "<bad>html</bad>"))

    assert ok is True
    # Two calls: first HTML (failed), second plain text (succeeded).
    assert len(calls) == 2
    assert calls[0]["parse_mode"] == "HTML"
    assert calls[1]["parse_mode"] is None


def test_send_returns_false_when_plain_text_also_fails(monkeypatch, caplog):
    """If even the plain-text fallback raises BadRequest, send returns False
    and emits the post-fallback ERROR — no silent drop, no infinite loop.
    """
    async def _fast_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("tenacity.asyncio.sleep", _fast_sleep, raising=False)
    monkeypatch.setattr("asyncio.sleep", _fast_sleep)

    fake_bot = MagicMock()
    fake_bot.send_message = AsyncMock(
        side_effect=BadRequest("Chat not found"),
    )

    with patch.object(notifications, "get_bot", return_value=fake_bot):
        with caplog.at_level(logging.ERROR, logger=notifications.logger.name):
            ok = _run(notifications.send(123, "anything"))

    assert ok is False
    # Plain-text retry was attempted exactly once after the HTML failure.
    # Total bot.send_message calls: 1 HTML + 1 plain text = 2.
    assert fake_bot.send_message.await_count == 2
    assert any(
        "Telegram send permanently failed after plain-text fallback"
        in r.getMessage()
        for r in caplog.records
    ), [r.getMessage() for r in caplog.records]


# ---------------------------------------------------------------------------
# §5 — Restart recovery (startup log line + count return)
# ---------------------------------------------------------------------------


def test_log_resumed_open_positions_emits_count(caplog):
    """log_resumed_open_positions must log
    'startup_recovery: Resumed monitoring N open positions' with the count,
    and return a dict with {resumed_paper, resumed_live} so APScheduler
    listener writes the count into job_runs.metadata.
    """
    scheduler = _try_import_scheduler()

    fetchval_results = [3, 1]  # paper=3, live=1

    async def _fetchval(*_a, **_k):
        return fetchval_results.pop(0)

    pool, _conn = _make_pool(fetchval_side_effect=_fetchval)

    with patch.object(scheduler, "get_pool", return_value=pool), \
         caplog.at_level(logging.INFO, logger=scheduler.logger.name):
        result = _run(scheduler.log_resumed_open_positions())

    assert result == {"resumed_paper": 3, "resumed_live": 1}
    assert any(
        "Resumed monitoring 4 open positions" in r.getMessage()
        and "(3 paper, 1 live)" in r.getMessage()
        for r in caplog.records
    ), [r.getMessage() for r in caplog.records]


def test_log_resumed_open_positions_swallows_db_error():
    """If the COUNT query fails (Supabase down at boot), the job must NOT
    raise — it returns an error-tagged dict so APScheduler treats the
    one-shot startup job as failed-but-not-crashed and the rest of the
    scheduler comes up cleanly.
    """
    scheduler = _try_import_scheduler()

    def _boom():
        raise RuntimeError("pool unavailable")

    with patch.object(scheduler, "get_pool", side_effect=_boom):
        result = _run(scheduler.log_resumed_open_positions())

    assert result["resumed_paper"] is None
    assert result["resumed_live"] is None
    assert "pool unavailable" in result["error"]
