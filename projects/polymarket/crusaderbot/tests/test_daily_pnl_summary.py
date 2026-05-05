"""Hermetic tests for the R12 daily P&L summary job.

Coverage:

  * format_summary renders + / - / 0 P&L correctly
  * is_summary_enabled defaults ON when the toggle row is missing
  * is_summary_enabled honours opt-out flag
  * set_summary_enabled upserts the toggle row
  * build_summary_for_user assembles realized/unrealized/fees/exposure
    from the underlying ledger + positions reads
  * run_once skips opted-out users without sending Telegram
  * run_once skips users with no Telegram id (counted separately)
  * run_once swallows per-user failures and continues the batch
  * run_once on empty user list returns 0/0/0 stats
  * scheduler registers the job under daily_pnl_summary.JOB_ID
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from projects.polymarket.crusaderbot.jobs import daily_pnl_summary as dp


USER_A = uuid4()
USER_B = uuid4()


# ---------- Pure formatter --------------------------------------------------


def test_format_summary_positive_amounts():
    out = dp.format_summary(
        date_label="2026-05-05",
        realized=Decimal("12.34"),
        unrealized=Decimal("4.50"),
        fees=Decimal("0.75"),
        open_count=2,
        exposure_pct=Decimal("23.4"),
        mode="LIVE",
    )
    assert "Realized P&L  : `+$12.34`" in out
    assert "Unrealized P&L: `+$4.50`" in out
    assert "Fees paid     : `$0.75`" in out
    assert "Open positions: `2`" in out
    assert "Exposure      : `23.4%`" in out
    assert "Mode          : `LIVE`" in out
    assert "2026-05-05" in out


def test_format_summary_negative_amounts():
    out = dp.format_summary(
        date_label="2026-05-05",
        realized=Decimal("-7.10"),
        unrealized=Decimal("-2.00"),
        fees=Decimal("0"),
        open_count=0,
        exposure_pct=Decimal("0"),
        mode="PAPER",
    )
    assert "`-$7.10`" in out
    assert "`-$2.00`" in out


def test_format_summary_zero_amounts():
    out = dp.format_summary(
        date_label="2026-05-05",
        realized=Decimal("0"),
        unrealized=Decimal("0"),
        fees=Decimal("0"),
        open_count=0,
        exposure_pct=Decimal("0"),
        mode="PAPER",
    )
    # Zero is rendered as +$0.00 by convention (>= 0 path).
    assert "`+$0.00`" in out


# ---------- Toggle persistence ----------------------------------------------


class _ToggleConn:
    def __init__(self, value: str | None = None) -> None:
        self.value = value
        self.executes: list[tuple[str, tuple]] = []

    async def fetchrow(self, query: str, *args: Any):
        if self.value is None:
            return None
        return {"value": self.value}

    async def execute(self, query: str, *args: Any):
        self.executes.append((query, args))
        if "INSERT INTO system_settings" in query:
            self.value = args[1]
        return "INSERT 0 1"

    async def fetchval(self, query: str, *args: Any):
        return None

    async def fetch(self, query: str, *args: Any):
        return []


class _Acquire:
    def __init__(self, conn) -> None:
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, et, e, tb):
        return False


class _Pool:
    def __init__(self, conn) -> None:
        self.conn = conn

    def acquire(self):
        return _Acquire(self.conn)


def test_is_summary_enabled_defaults_on_when_row_missing():
    conn = _ToggleConn(value=None)
    with patch.object(dp, "get_pool", return_value=_Pool(conn)):
        assert asyncio.run(dp.is_summary_enabled(USER_A)) is True


def test_is_summary_enabled_returns_false_when_opted_out():
    conn = _ToggleConn(value="true")
    with patch.object(dp, "get_pool", return_value=_Pool(conn)):
        assert asyncio.run(dp.is_summary_enabled(USER_A)) is False


def test_is_summary_enabled_returns_true_when_explicit_false():
    conn = _ToggleConn(value="false")
    with patch.object(dp, "get_pool", return_value=_Pool(conn)):
        assert asyncio.run(dp.is_summary_enabled(USER_A)) is True


def test_set_summary_enabled_upserts_toggle():
    conn = _ToggleConn(value=None)
    with patch.object(dp, "get_pool", return_value=_Pool(conn)):
        asyncio.run(dp.set_summary_enabled(USER_A, False))
    inserts = [args for q, args in conn.executes
               if "INSERT INTO system_settings" in q]
    assert len(inserts) == 1
    assert inserts[0] == (f"daily_summary_off:{USER_A}", "true")


def test_set_summary_enabled_persist_true_writes_off_false():
    conn = _ToggleConn(value=None)
    with patch.object(dp, "get_pool", return_value=_Pool(conn)):
        asyncio.run(dp.set_summary_enabled(USER_A, True))
    args = conn.executes[0][1]
    assert args[1] == "false"  # OFF flag = false → ON


# ---------- build_summary_for_user end-to-end shape -------------------------


class _SummaryConn:
    def __init__(self, *, realized: float, fees: float, balance: float,
                 mode: str, positions: list[dict]) -> None:
        self.realized = realized
        self.fees = fees
        self.balance = balance
        self.mode = mode
        self.positions = positions

    async def fetchval(self, query: str, *args: Any):
        # Realized P&L now sums positions.pnl_usdc (closed today) — NOT
        # the ledger — because trade_close ledger entries credit full
        # proceeds (size + pnl) rather than P&L itself.
        if "SUM(pnl_usdc)" in query and "FROM positions" in query:
            return Decimal(str(self.realized))
        if "type = 'fee'" in query:
            return Decimal(str(self.fees))
        if "balance_usdc" in query:
            return Decimal(str(self.balance))
        if "trading_mode" in query:
            return self.mode
        return 0

    async def fetch(self, query: str, *args: Any):
        # The OPEN-positions read pulls side / entry / current for the
        # unrealized P&L computation. Distinguish from the closed-today
        # realized read (a SUM(pnl_usdc), not a row fetch) by the
        # column projection.
        if "FROM positions" in query and "side, size_usdc" in query:
            return self.positions
        return []

    async def fetchrow(self, query: str, *args: Any):
        return None

    async def execute(self, query: str, *args: Any):
        return "OK"


def test_build_summary_for_user_assembles_lines():
    conn = _SummaryConn(
        # Realized is now the SUM of positions.pnl_usdc closed today —
        # i.e. profit, not proceeds. A $100 position closed for $110
        # contributes +10 here, NOT +110.
        realized=10.0,
        fees=-0.50,  # ledger stores fees as negative debits
        balance=100.0,
        mode="paper",
        positions=[
            # YES side: entry 0.5, current 0.6, size 20 → ret +0.2 → +$4.0
            {"side": "yes", "size_usdc": Decimal("20"),
             "entry_price": Decimal("0.5"),
             "current_price": Decimal("0.6")},
            # NO side: entry 0.4, current 0.3, size 10 →
            # comp_entry=0.6 comp_current=0.7 ret=+0.1666 → +$1.6666...
            {"side": "no", "size_usdc": Decimal("10"),
             "entry_price": Decimal("0.4"),
             "current_price": Decimal("0.3")},
        ],
    )
    with patch.object(dp, "get_pool", return_value=_Pool(conn)):
        out = asyncio.run(dp.build_summary_for_user(USER_A, "2026-05-05"))
    assert "+$10.00" in out  # realized
    assert "$0.50" in out  # fees (abs)
    assert "Open positions: `2`" in out
    assert "Exposure      : `30.0%`" in out
    assert "PAPER" in out
    # Unrealized = $4.00 + $1.67 ≈ $5.67 (Decimal precision dependent)
    assert "+$5." in out


def test_realized_pnl_query_targets_positions_pnl_usdc_not_ledger():
    """Codex P2 regression: realized P&L must come from positions.pnl_usdc,
    not from summing ledger trade_close (which credits full proceeds).
    """
    captured: list[str] = []

    class _CaptureConn:
        async def fetchval(self, query: str, *args: Any):
            captured.append(query)
            if "SUM(pnl_usdc)" in query:
                return Decimal("0")
            return Decimal("0")

        async def fetch(self, query: str, *args: Any):
            return []

        async def fetchrow(self, query: str, *args: Any):
            return None

        async def execute(self, query: str, *args: Any):
            return "OK"

    with patch.object(dp, "get_pool", return_value=_Pool(_CaptureConn())):
        asyncio.run(dp.build_summary_for_user(USER_A, "2026-05-05"))
    realized_queries = [q for q in captured
                        if "SUM(pnl_usdc)" in q and "FROM positions" in q]
    assert realized_queries, (
        "realized P&L must read from positions.pnl_usdc — saw queries: "
        + repr(captured)
    )
    # No ledger-based realized query should remain.
    bad = [q for q in captured
           if "SUM(amount_usdc)" in q and "trade_close" in q]
    assert not bad, (
        "realized P&L must NOT sum ledger trade_close (proceeds, not "
        f"P&L). Found: {bad!r}"
    )


def test_build_summary_handles_missing_balance_zero_exposure():
    conn = _SummaryConn(
        realized=0, fees=0, balance=0, mode="live", positions=[],
    )
    with patch.object(dp, "get_pool", return_value=_Pool(conn)):
        out = asyncio.run(dp.build_summary_for_user(USER_A, "2026-05-05"))
    assert "Exposure      : `0.0%`" in out
    assert "Mode          : `LIVE`" in out


# ---------- run_once batch behaviour ----------------------------------------


def test_run_once_empty_user_list_returns_zero_stats():
    with patch.object(dp, "_list_recipient_users",
                      AsyncMock(return_value=[])):
        out = asyncio.run(dp.run_once())
    assert out["sent"] == 0
    assert out["failed"] == 0
    assert out["skipped_disabled"] == 0
    assert out["total_users"] == 0


def test_run_once_skips_opted_out_users():
    users = [{"id": USER_A, "telegram_user_id": 100},
             {"id": USER_B, "telegram_user_id": 200}]
    sent_messages: list[tuple[int, str]] = []

    async def fake_send(chat_id, text, *args, **kwargs):
        sent_messages.append((chat_id, text))
        return True

    async def fake_enabled(uid):
        return uid == USER_A  # only A receives

    with patch.object(dp, "_list_recipient_users",
                      AsyncMock(return_value=users)), \
         patch.object(dp, "is_summary_enabled", side_effect=fake_enabled), \
         patch.object(dp, "build_summary_for_user",
                      AsyncMock(return_value="msg")), \
         patch.object(dp.notifications, "send", side_effect=fake_send):
        out = asyncio.run(dp.run_once())
    assert out["sent"] == 1
    assert out["skipped_disabled"] == 1
    assert sent_messages == [(100, "msg")]


def test_run_once_skips_users_without_telegram_id():
    users = [{"id": USER_A, "telegram_user_id": None}]
    with patch.object(dp, "_list_recipient_users",
                      AsyncMock(return_value=users)), \
         patch.object(dp, "is_summary_enabled",
                      AsyncMock(return_value=True)), \
         patch.object(dp.notifications, "send",
                      AsyncMock(return_value=True)):
        out = asyncio.run(dp.run_once())
    assert out["sent"] == 0
    assert out["skipped_no_telegram"] == 1


def test_run_once_continues_after_per_user_failure():
    users = [{"id": USER_A, "telegram_user_id": 100},
             {"id": USER_B, "telegram_user_id": 200}]
    call_log: list = []

    async def fake_build(uid, _date):
        if uid == USER_A:
            raise RuntimeError("DB blip on A")
        call_log.append(uid)
        return "msg"

    async def fake_send(chat_id, text, *args, **kwargs):
        return True

    with patch.object(dp, "_list_recipient_users",
                      AsyncMock(return_value=users)), \
         patch.object(dp, "is_summary_enabled",
                      AsyncMock(return_value=True)), \
         patch.object(dp, "build_summary_for_user", side_effect=fake_build), \
         patch.object(dp.notifications, "send", side_effect=fake_send):
        out = asyncio.run(dp.run_once())
    # User B still got their message even though A errored.
    assert call_log == [USER_B]
    assert out["sent"] == 1
    assert out["failed"] == 1


def test_run_once_counts_telegram_send_returning_false_as_failed():
    users = [{"id": USER_A, "telegram_user_id": 100}]
    with patch.object(dp, "_list_recipient_users",
                      AsyncMock(return_value=users)), \
         patch.object(dp, "is_summary_enabled",
                      AsyncMock(return_value=True)), \
         patch.object(dp, "build_summary_for_user",
                      AsyncMock(return_value="msg")), \
         patch.object(dp.notifications, "send",
                      AsyncMock(return_value=False)):
        out = asyncio.run(dp.run_once())
    assert out["sent"] == 0
    assert out["failed"] == 1


# ---------- Scheduler registration ------------------------------------------


def test_scheduler_registers_daily_pnl_summary_job():
    """Smoke test: setup_scheduler() registers a cron job under JOB_ID."""
    from projects.polymarket.crusaderbot import scheduler

    class _SettingsStub:
        TIMEZONE = "Asia/Jakarta"
        MARKET_SCAN_INTERVAL = 300
        DEPOSIT_WATCH_INTERVAL = 120
        SIGNAL_SCAN_INTERVAL = 180
        EXIT_WATCH_INTERVAL = 60
        REDEEM_INTERVAL = 3600
        RESOLUTION_CHECK_INTERVAL = 300

    with patch.object(scheduler, "get_settings", return_value=_SettingsStub()):
        sched = scheduler.setup_scheduler()
    job = sched.get_job(dp.JOB_ID)
    assert job is not None
    # Stored as a CronTrigger — confirm hour=23 minute=0.
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert fields.get("hour") == "23"
    assert fields.get("minute") == "0"
