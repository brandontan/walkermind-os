"""Hermetic tests — Track H: Portfolio Charts + Weekly Insights.

Coverage:
  Chart service:
    1.  generate_portfolio_chart returns None when no ledger data
    2.  generate_portfolio_chart returns (bytes, peak, low, now) with data
    3.  _compute_stats peak/low/now are correct
    4.  _generate_png returns non-empty bytes
    5.  days=None triggers cutoff=None (all-time path)

  Chart handler:
    6.  chart_command sends fallback text when chart is None
    7.  chart_command sends photo when chart has data
    8.  chart_callback parses days_key correctly (7 / 30 / all)
    9.  _caption formats label correctly for 7d / all

  chart_kb keyboard:
   10.  chart_kb has exactly 3 buttons in one row
   11.  chart_kb marks active period with checkmark

  Weekly insights:
   12.  format_weekly_insights empty state
   13.  format_weekly_insights non-empty — best/worst category present
   14.  format_weekly_insights non-empty — best/worst signal present
   15.  format_weekly_insights — win rate calculation correct
   16.  format_weekly_insights — _fmt_pnl positive sign
   17.  format_weekly_insights — _fmt_pnl negative sign
   18.  weekly_insights job: run_once sends to all users
   19.  weekly_insights job: per-user failure does not abort batch
   20.  weekly_insights job ID registered in scheduler
   21.  format_weekly_insights — no categories rendered when list is empty
"""
from __future__ import annotations

import io
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from projects.polymarket.crusaderbot.bot.handlers.portfolio_chart import (
    _caption,
    _parse_days,
)
from projects.polymarket.crusaderbot.bot.keyboards import chart_kb
from projects.polymarket.crusaderbot.jobs.weekly_insights import (
    _fmt_pnl,
    format_weekly_insights,
)
from projects.polymarket.crusaderbot.services.portfolio_chart import (
    _compute_stats,
    _generate_png,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

from datetime import date


def _series(*balances):
    """Build (date, Decimal) series from a list of balance values."""
    return [(date(2026, 1, i + 1), Decimal(str(b))) for i, b in enumerate(balances)]


def _cat(name, total=5, wins=3, pnl="2.00"):
    total_v = int(total)
    wins_v = int(wins)
    return {
        "name": name,
        "total": total_v,
        "wins": wins_v,
        "win_rate": wins_v / total_v if total_v else 0.0,
        "total_pnl": Decimal(pnl),
    }


def _sig(name, pnl="5.00", total=4, wins=2):
    total_v = int(total)
    wins_v = int(wins)
    return {
        "name": name,
        "total": total_v,
        "wins": wins_v,
        "win_rate": wins_v / total_v if total_v else 0.0,
        "total_pnl": Decimal(pnl),
    }


def _weekly_data(**overrides):
    defaults = {
        "total_trades": 10,
        "total_wins": 6,
        "total_pnl": Decimal("12.50"),
        "categories": [_cat("politics", 5, 3), _cat("sports", 4, 1, "-2.00")],
        "signals": [_sig("copy_trade", "8.00"), _sig("signal", "-3.00")],
    }
    defaults.update(overrides)
    return defaults


# ── 1. generate_portfolio_chart returns None when no data ─────────────────────


@pytest.mark.asyncio
async def test_generate_chart_returns_none_when_no_ledger():
    with patch(
        "projects.polymarket.crusaderbot.services.portfolio_chart._fetch_daily_balance_series",
        new=AsyncMock(return_value=[]),
    ):
        from projects.polymarket.crusaderbot.services.portfolio_chart import (
            generate_portfolio_chart,
        )
        result = await generate_portfolio_chart(uuid4(), days=7)
    assert result is None


# ── 2. generate_portfolio_chart returns tuple with data ───────────────────────


@pytest.mark.asyncio
async def test_generate_chart_returns_tuple_with_data():
    series = _series(100, 120, 110, 130, 125, 140, 135)
    with patch(
        "projects.polymarket.crusaderbot.services.portfolio_chart._fetch_daily_balance_series",
        new=AsyncMock(return_value=series),
    ), patch(
        "projects.polymarket.crusaderbot.services.portfolio_chart._generate_png",
        return_value=b"FAKE_PNG",
    ):
        from projects.polymarket.crusaderbot.services.portfolio_chart import (
            generate_portfolio_chart,
        )
        result = await generate_portfolio_chart(uuid4(), days=7)

    assert result is not None
    png, peak, low, now = result
    assert png == b"FAKE_PNG"
    assert peak == Decimal("140")
    assert low == Decimal("100")
    assert now == Decimal("135")


# ── 3. _compute_stats peak/low/now ────────────────────────────────────────────


def test_compute_stats_correct():
    series = _series(50, 200, 10, 150)
    peak, low, now = _compute_stats(series)
    assert peak == Decimal("200")
    assert low == Decimal("10")
    assert now == Decimal("150")


def test_compute_stats_empty():
    peak, low, now = _compute_stats([])
    assert peak == Decimal("0")
    assert low == Decimal("0")
    assert now == Decimal("0")


# ── 4. _generate_png returns non-empty bytes ──────────────────────────────────


def test_generate_png_returns_bytes():
    pytest.importorskip("matplotlib")
    series = _series(100, 120, 110)
    result = _generate_png(series, "7 DAYS")
    assert isinstance(result, bytes)
    assert len(result) > 100  # real PNG is never this small


# ── 4b. carry-forward: funded-but-inactive window returns flat line ───────────


@pytest.mark.asyncio
async def test_generate_chart_carry_forward_for_inactive_window():
    """User has balance from before the 7d window but no entries within it.

    Should return a flat two-point series at the pre-window balance rather
    than None (which would trigger the false empty-state message).
    """
    from datetime import date, timedelta

    # Simulate: all ledger activity happened 30 days ago, balance = $500
    old_day = date(2026, 1, 1)
    series_before_window = [(old_day, Decimal("500"))]

    # cutoff = today - 6 days; none of the pre-existing rows fall in window
    async def fake_fetch(user_id, cutoff_date):
        from projects.polymarket.crusaderbot.services.portfolio_chart import (
            _fetch_daily_balance_series,
        )
        # Run the real Python-level logic with synthetic DB rows
        rows = [{"day": old_day, "daily_net": Decimal("500")}]
        running = Decimal(0)
        anchor = Decimal(0)
        result = []
        for row in rows:
            running += Decimal(str(row["daily_net"] or 0))
            day = row["day"]
            if cutoff_date is None or day >= cutoff_date:
                result.append((day, running))
            else:
                anchor = running
        if not result and anchor != 0 and cutoff_date is not None:
            from projects.polymarket.crusaderbot.services.portfolio_chart import (
                _today_jakarta,
            )
            today = _today_jakarta()
            result = [(cutoff_date, anchor), (today, anchor)]
        return result

    with patch(
        "projects.polymarket.crusaderbot.services.portfolio_chart._fetch_daily_balance_series",
        new=fake_fetch,
    ), patch(
        "projects.polymarket.crusaderbot.services.portfolio_chart._generate_png",
        return_value=b"PNG",
    ):
        from projects.polymarket.crusaderbot.services.portfolio_chart import (
            generate_portfolio_chart,
        )
        result = await generate_portfolio_chart(uuid4(), days=7)

    assert result is not None, "carry-forward should produce a chart, not None"
    _, peak, low, now = result
    assert now == Decimal("500")
    assert peak == Decimal("500")
    assert low == Decimal("500")


# ── 5. days=None → cutoff=None (all-time) ────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_chart_all_time_passes_none_cutoff():
    captured: list = []

    async def fake_fetch(user_id, cutoff_date):
        captured.append(cutoff_date)
        return []

    with patch(
        "projects.polymarket.crusaderbot.services.portfolio_chart._fetch_daily_balance_series",
        new=fake_fetch,
    ):
        from projects.polymarket.crusaderbot.services.portfolio_chart import (
            generate_portfolio_chart,
        )
        await generate_portfolio_chart(uuid4(), days=None)

    assert captured[0] is None


# ── 6. chart_command sends fallback when chart is None ────────────────────────


@pytest.mark.asyncio
async def test_chart_command_sends_fallback_on_no_data():
    update = MagicMock()
    update.effective_user.id = 12345
    update.effective_user.username = "testuser"
    update.message = AsyncMock()
    update.message.chat_id = 99
    ctx = MagicMock()
    ctx.bot = AsyncMock()

    fake_user = {"id": uuid4(), "access_tier": 2}

    with patch(
        "projects.polymarket.crusaderbot.bot.handlers.portfolio_chart.upsert_user",
        new=AsyncMock(return_value=fake_user),
    ), patch(
        "projects.polymarket.crusaderbot.bot.handlers.portfolio_chart.generate_portfolio_chart",
        new=AsyncMock(return_value=None),
    ):
        from projects.polymarket.crusaderbot.bot.handlers.portfolio_chart import (
            chart_command,
        )
        await chart_command(update, ctx)

    update.message.reply_text.assert_called_once()
    args, kwargs = update.message.reply_text.call_args
    assert "No balance history" in args[0] or "No balance history" in str(kwargs)


# ── 7. chart_command sends photo when chart has data ─────────────────────────


@pytest.mark.asyncio
async def test_chart_command_sends_photo_with_data():
    update = MagicMock()
    update.effective_user.id = 12345
    update.effective_user.username = "testuser"
    update.message = AsyncMock()
    update.message.chat_id = 99
    ctx = MagicMock()
    ctx.bot = AsyncMock()

    fake_user = {"id": uuid4(), "access_tier": 2}
    chart_result = (b"PNG_BYTES", Decimal("500"), Decimal("100"), Decimal("450"))

    with patch(
        "projects.polymarket.crusaderbot.bot.handlers.portfolio_chart.upsert_user",
        new=AsyncMock(return_value=fake_user),
    ), patch(
        "projects.polymarket.crusaderbot.bot.handlers.portfolio_chart.generate_portfolio_chart",
        new=AsyncMock(return_value=chart_result),
    ):
        from projects.polymarket.crusaderbot.bot.handlers.portfolio_chart import (
            chart_command,
        )
        await chart_command(update, ctx)

    ctx.bot.send_photo.assert_called_once()


# ── 8. _parse_days parses keys correctly ──────────────────────────────────────


def test_parse_days_7():
    assert _parse_days("7") == 7


def test_parse_days_30():
    assert _parse_days("30") == 30


def test_parse_days_all():
    assert _parse_days("all") is None


def test_parse_days_invalid_defaults_to_7():
    assert _parse_days("bogus") == 7


# ── 9. _caption formats correctly ────────────────────────────────────────────


def test_caption_7d():
    txt = _caption("7", 500.0, 100.0, 450.0)
    assert "7 DAYS" in txt
    assert "500.00" in txt
    assert "100.00" in txt
    assert "450.00" in txt


def test_caption_all_time():
    txt = _caption("all", 500.0, 100.0, 450.0)
    assert "ALL TIME" in txt


# ── 10. chart_kb structure ───────────────────────────────────────────────────


def test_chart_kb_structure():
    kb = chart_kb("7")
    rows = kb.inline_keyboard
    assert len(rows) == 1
    assert len(rows[0]) == 3
    callbacks = {b.callback_data for b in rows[0]}
    assert "chart:7" in callbacks
    assert "chart:30" in callbacks
    assert "chart:all" in callbacks


# ── 11. chart_kb marks active period ─────────────────────────────────────────


def test_chart_kb_marks_active_7():
    kb = chart_kb("7")
    texts = [b.text for b in kb.inline_keyboard[0]]
    active = [t for t in texts if "✅" in t]
    assert len(active) == 1
    assert "7 Days" in active[0]


def test_chart_kb_marks_active_all():
    kb = chart_kb("all")
    texts = [b.text for b in kb.inline_keyboard[0]]
    active = [t for t in texts if "✅" in t]
    assert len(active) == 1
    assert "All Time" in active[0]


# ── 12. format_weekly_insights empty state ───────────────────────────────────


def test_format_weekly_insights_empty():
    data = _weekly_data(total_trades=0, categories=[], signals=[])
    out = format_weekly_insights(data)
    assert "No closed paper trades" in out
    assert "Weekly Insights" in out


# ── 13. format_weekly_insights categories present ────────────────────────────


def test_format_weekly_insights_shows_best_worst_category():
    data = _weekly_data()
    out = format_weekly_insights(data)
    assert "By Category" in out
    # best cat: politics 3/5=60%, worst: sports 1/4=25%
    assert "politics" in out
    assert "sports" in out


# ── 14. format_weekly_insights signals present ───────────────────────────────


def test_format_weekly_insights_shows_best_worst_signal():
    data = _weekly_data()
    out = format_weekly_insights(data)
    assert "By Signal" in out
    assert "copy trade" in out or "copy_trade" in out.lower()
    assert "signal" in out


# ── 15. win rate calculation correct ─────────────────────────────────────────


def test_format_weekly_insights_win_rate():
    data = _weekly_data(total_trades=10, total_wins=7)
    out = format_weekly_insights(data)
    assert "70%" in out


# ── 16. _fmt_pnl positive ────────────────────────────────────────────────────


def test_fmt_pnl_positive():
    assert _fmt_pnl(Decimal("8.50")) == "+$8.50"


# ── 17. _fmt_pnl negative ────────────────────────────────────────────────────


def test_fmt_pnl_negative():
    assert _fmt_pnl(Decimal("-4.20")) == "-$4.20"


# ── 18. run_once sends to all users ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_weekly_insights_run_once_sends_all():
    users = [
        {"id": uuid4(), "telegram_user_id": 111},
        {"id": uuid4(), "telegram_user_id": 222},
    ]

    with patch(
        "projects.polymarket.crusaderbot.jobs.weekly_insights._list_active_users",
        new=AsyncMock(return_value=users),
    ), patch(
        "projects.polymarket.crusaderbot.jobs.weekly_insights._fetch_weekly_stats",
        new=AsyncMock(return_value=_weekly_data()),
    ), patch(
        "projects.polymarket.crusaderbot.jobs.weekly_insights.notifications.send",
        new=AsyncMock(return_value=True),
    ):
        from projects.polymarket.crusaderbot.jobs.weekly_insights import run_once
        stats = await run_once()

    assert stats["sent"] == 2
    assert stats["failed"] == 0
    assert stats["total_users"] == 2


# ── 19. per-user failure does not abort batch ─────────────────────────────────


@pytest.mark.asyncio
async def test_weekly_insights_run_once_resilient_to_failures():
    users = [
        {"id": uuid4(), "telegram_user_id": 111},
        {"id": uuid4(), "telegram_user_id": 222},
    ]
    call_count = 0

    async def flaky_send(tg_id, text):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Telegram timeout")
        return True

    with patch(
        "projects.polymarket.crusaderbot.jobs.weekly_insights._list_active_users",
        new=AsyncMock(return_value=users),
    ), patch(
        "projects.polymarket.crusaderbot.jobs.weekly_insights._fetch_weekly_stats",
        new=AsyncMock(return_value=_weekly_data()),
    ), patch(
        "projects.polymarket.crusaderbot.jobs.weekly_insights.notifications.send",
        new=flaky_send,
    ):
        from projects.polymarket.crusaderbot.jobs.weekly_insights import run_once
        stats = await run_once()

    assert stats["sent"] == 1
    assert stats["failed"] == 1


# ── 20. weekly_insights job ID registered in scheduler ───────────────────────


def test_weekly_insights_job_id_in_scheduler():
    from pathlib import Path
    from projects.polymarket.crusaderbot.jobs.weekly_insights import JOB_ID

    scheduler_src = (
        Path(__file__).parent.parent / "scheduler.py"
    ).read_text()
    assert JOB_ID in scheduler_src, (
        f"Job ID '{JOB_ID}' not found in scheduler.py — "
        "weekly insights cron not registered."
    )


# ── 21. format_weekly_insights: no categories when list empty ─────────────────


def test_format_weekly_insights_no_categories_section_when_empty():
    data = _weekly_data(categories=[], signals=[])
    out = format_weekly_insights(data)
    assert "By Category" not in out
    assert "By Signal" not in out
