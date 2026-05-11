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
    # Track E (#960): activity today (closed_today>0) keeps the full
    # format so the negative-amount rendering can be asserted. The
    # no-trade empty state would otherwise hide the P&L lines.
    out = dp.format_summary(
        date_label="2026-05-05",
        realized=Decimal("-7.10"),
        unrealized=Decimal("-2.00"),
        fees=Decimal("0"),
        open_count=0,
        exposure_pct=Decimal("0"),
        mode="PAPER",
        closed_today=1,
        losses_today=1,
    )
    assert "`-$7.10`" in out
    assert "`-$2.00`" in out


def test_format_summary_zero_amounts_when_activity_present():
    # Track E (#960): when activity occurred today, the full format
    # still renders zero P&L as +$0.00 (>= 0 path) rather than the
    # no-trade empty state. open_count > 0 keeps us in full format.
    out = dp.format_summary(
        date_label="2026-05-05",
        realized=Decimal("0"),
        unrealized=Decimal("0"),
        fees=Decimal("0"),
        open_count=1,
        exposure_pct=Decimal("0"),
        mode="PAPER",
    )
    assert "`+$0.00`" in out
    assert "No paper trades today" not in out


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
            # YES position. Entry/current are side-specific (YES price).
            # entry 0.5, current 0.6, size 20 → ret +0.2 → +$4.0
            {"side": "yes", "size_usdc": Decimal("20"),
             "entry_price": Decimal("0.5"),
             "current_price": Decimal("0.6")},
            # NO position. Entry/current are side-specific (NO price) —
            # registry.update_current_price persists the NO mark for NO
            # rows. Bought NO at 0.4, NO market dropped to 0.3 → loss.
            # ret = (0.3 - 0.4) / 0.4 = -0.25 → -$2.50
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
    # Unrealized = $4.00 (YES gain) + (-$2.50) (NO loss) = +$1.50
    assert "+$1.50" in out


def test_no_side_unrealized_gain_when_no_price_rises():
    """Codex P2 regression: a NO position bought at NO=0.40 and marked
    at NO=0.60 must show an UNREALIZED GAIN, not a loss.

    The previous complement formula treated entry/current as YES-side
    probabilities and inverted the sign for NO holdings. Prices are
    actually stored side-specifically (registry.update_current_price
    persists the NO mark for NO rows), so a direct
    (current - entry) / entry formula is required for both sides.
    """
    conn = _SummaryConn(
        realized=0.0, fees=0.0, balance=100.0, mode="paper",
        positions=[
            # Bought NO at 0.40 with $40 USDC → 100 NO shares.
            # NO mark rises to 0.60 → shares worth $60 → +$20 gain.
            {"side": "no", "size_usdc": Decimal("40"),
             "entry_price": Decimal("0.4"),
             "current_price": Decimal("0.6")},
        ],
    )
    with patch.object(dp, "get_pool", return_value=_Pool(conn)):
        out = asyncio.run(dp.build_summary_for_user(USER_A, "2026-05-05"))
    # Expected unrealized = (0.60 - 0.40) / 0.40 * 40 = +$20.00
    assert "Unrealized P&L: `+$20.00`" in out, out


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
    # An open position keeps us in full format (open_count > 0) so the
    # exposure line is exercised. With balance=0 the exposure_pct is
    # forced to 0.0% to avoid division by zero.
    conn = _SummaryConn(
        realized=0, fees=0, balance=0, mode="live",
        positions=[
            {"side": "yes", "size_usdc": Decimal("5"),
             "entry_price": Decimal("0.5"),
             "current_price": Decimal("0.5")},
        ],
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
        ORDER_POLL_INTERVAL_SECONDS = 30
        WS_WATCHDOG_INTERVAL_SECONDS = 60
        COPY_TRADE_MONITOR_INTERVAL = 60

    with patch.object(scheduler, "get_settings", return_value=_SettingsStub()):
        sched = scheduler.setup_scheduler()
    job = sched.get_job(dp.JOB_ID)
    assert job is not None
    # Stored as a CronTrigger — confirm hour=23 minute=0.
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert fields.get("hour") == "23"
    assert fields.get("minute") == "0"


# ---------- Fast Track Track E (#960): paper-mode counts + no-trade state ---


def test_format_summary_no_trade_state_renders_compact_line():
    """Track E: zero activity AND zero open positions → compact form."""
    out = dp.format_summary(
        date_label="2026-05-05",
        realized=Decimal("0"),
        unrealized=Decimal("0"),
        fees=Decimal("0"),
        open_count=0,
        exposure_pct=Decimal("0"),
        mode="PAPER",
        opened_today=0,
        closed_today=0,
        wins_today=0,
        losses_today=0,
    )
    assert "No paper trades today" in out
    assert "Mode: `PAPER`" in out
    # Full-format rows must NOT leak into the compact form.
    assert "Realized P&L" not in out
    assert "Exposure" not in out


def test_format_summary_no_trade_state_skipped_when_position_open():
    """An open position keeps the full format even with zero trades today."""
    out = dp.format_summary(
        date_label="2026-05-05",
        realized=Decimal("0"),
        unrealized=Decimal("1.50"),
        fees=Decimal("0"),
        open_count=1,
        exposure_pct=Decimal("5.0"),
        mode="PAPER",
        opened_today=0,
        closed_today=0,
    )
    assert "Realized P&L" in out
    assert "Trades opened : `0`" in out
    assert "Trades closed : `0` (W:0 L:0)" in out
    assert "No paper trades today" not in out


def test_format_summary_includes_trade_counts_with_wl_breakdown():
    """Counts line surfaces opened/closed plus W/L breakdown."""
    out = dp.format_summary(
        date_label="2026-05-05",
        realized=Decimal("8.00"),
        unrealized=Decimal("0"),
        fees=Decimal("0.30"),
        open_count=2,
        exposure_pct=Decimal("12.5"),
        mode="PAPER",
        opened_today=4,
        closed_today=3,
        wins_today=2,
        losses_today=1,
    )
    assert "Trades opened : `4`" in out
    assert "Trades closed : `3` (W:2 L:1)" in out
    # Existing R12 lines remain.
    assert "Realized P&L  : `+$8.00`" in out
    assert "Open positions: `2`" in out


def test_build_summary_paper_counts_aggregated_via_counts_row():
    """_fetch_user_summary_row pulls paper-mode counts from the counts query."""

    class _CountsConn(_SummaryConn):
        def __init__(self, *, counts: dict, **kwargs):
            super().__init__(**kwargs)
            self._counts = counts

        async def fetchrow(self, query: str, *args: Any):
            if "opened_today" in query and "closed_today" in query:
                return self._counts
            return None

    conn = _CountsConn(
        realized=5.0, fees=0, balance=100.0, mode="paper",
        positions=[
            {"side": "yes", "size_usdc": Decimal("10"),
             "entry_price": Decimal("0.5"),
             "current_price": Decimal("0.5")},
        ],
        counts={"opened_today": 3, "closed_today": 2,
                "wins_today": 1, "losses_today": 1},
    )
    with patch.object(dp, "get_pool", return_value=_Pool(conn)):
        out = asyncio.run(dp.build_summary_for_user(USER_A, "2026-05-05"))
    assert "Trades opened : `3`" in out
    assert "Trades closed : `2` (W:1 L:1)" in out


def test_build_summary_no_trade_state_on_empty_paper_history():
    """No paper trades today AND no open positions → compact summary."""

    class _EmptyConn(_SummaryConn):
        async def fetchrow(self, query: str, *args: Any):
            if "opened_today" in query and "closed_today" in query:
                return {"opened_today": 0, "closed_today": 0,
                        "wins_today": 0, "losses_today": 0}
            return None

    conn = _EmptyConn(
        realized=0, fees=0, balance=100.0, mode="paper", positions=[],
    )
    with patch.object(dp, "get_pool", return_value=_Pool(conn)):
        out = asyncio.run(dp.build_summary_for_user(USER_A, "2026-05-05"))
    assert "No paper trades today" in out
    assert "Realized P&L" not in out


def test_build_summary_counts_query_filters_paper_mode():
    """The counts query must scope to mode='paper' so live trades never
    leak into the Fast Track paper summary breakdown."""
    captured: list[str] = []

    class _CaptureConn:
        async def fetchval(self, query: str, *args: Any):
            return Decimal("0")

        async def fetch(self, query: str, *args: Any):
            return []

        async def fetchrow(self, query: str, *args: Any):
            captured.append(query)
            return {"opened_today": 0, "closed_today": 0,
                    "wins_today": 0, "losses_today": 0}

        async def execute(self, query: str, *args: Any):
            return "OK"

    with patch.object(dp, "get_pool", return_value=_Pool(_CaptureConn())):
        asyncio.run(dp.build_summary_for_user(USER_A, "2026-05-05"))
    counts_queries = [q for q in captured
                      if "opened_today" in q and "closed_today" in q]
    assert counts_queries, (
        "counts query missing from build_summary_for_user — got: "
        + repr(captured)
    )
    # Every paper-mode counter must filter mode='paper'.
    q = counts_queries[0]
    assert q.count("mode='paper'") >= 4, (
        f"counts query must filter mode='paper' on all four counters: {q!r}"
    )


def test_scheduler_registers_run_job_as_daily_callable():
    """Track E callback wiring: APScheduler job must dispatch run_job."""
    from projects.polymarket.crusaderbot import scheduler

    class _SettingsStub:
        TIMEZONE = "Asia/Jakarta"
        MARKET_SCAN_INTERVAL = 300
        DEPOSIT_WATCH_INTERVAL = 120
        SIGNAL_SCAN_INTERVAL = 180
        EXIT_WATCH_INTERVAL = 60
        REDEEM_INTERVAL = 3600
        RESOLUTION_CHECK_INTERVAL = 300
        ORDER_POLL_INTERVAL_SECONDS = 30
        WS_WATCHDOG_INTERVAL_SECONDS = 60
        COPY_TRADE_MONITOR_INTERVAL = 60

    with patch.object(scheduler, "get_settings", return_value=_SettingsStub()):
        sched = scheduler.setup_scheduler()
    job = sched.get_job(dp.JOB_ID)
    assert job is not None
    assert job.func is dp.run_job, (
        f"scheduler must dispatch daily_pnl_summary.run_job, got {job.func!r}"
    )


def test_run_job_invokes_run_once_callback_path():
    """run_job is a thin wrapper that defers to run_once and logs stats."""
    captured: dict = {}

    async def fake_run_once():
        captured["called"] = True
        return {"sent": 1, "skipped_disabled": 0,
                "skipped_no_telegram": 0, "failed": 0,
                "total_users": 1, "date": "2026-05-05"}

    with patch.object(dp, "run_once", side_effect=fake_run_once):
        asyncio.run(dp.run_job())
    assert captured.get("called") is True
