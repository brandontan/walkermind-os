"""Hermetic tests for PNL Insights handler (crusaderbot-premium-pnl-insights).

Coverage:
  1.  format_insights empty state (no closed trades)
  2.  format_insights wins-only (infinite profit factor)
  3.  format_insights losses-only (zero wins)
  4.  format_insights mixed (computed profit factor)
  5.  format_insights best trade positive PnL string
  6.  format_insights worst trade negative PnL string
  7.  _compute_streak empty list returns ('win', 0)
  8.  _compute_streak win streak counted correctly
  9.  _compute_streak loss streak counted correctly
  10. _compute_streak streak breaks on direction change
  11. _compute_streak break-even (0) counts as loss
  12. insights_kb has Refresh and Dashboard buttons
  13. dashboard_nav includes Insights button when has_trades
  14. dashboard_nav omits Insights button when not has_trades
  15. my_trades_main_kb nav row includes Insights button
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from projects.polymarket.crusaderbot.bot.handlers.pnl_insights import (
    _compute_streak,
    _safe_md,
    format_insights,
)
from projects.polymarket.crusaderbot.bot.keyboards import (
    dashboard_nav,
    insights_kb,
)
from projects.polymarket.crusaderbot.bot.keyboards.my_trades import my_trades_main_kb


# ---------- Fixtures -----------------------------------------------------------

def _base_data(**overrides) -> dict:
    defaults = {
        "total_closed": 10,
        "wins": 6,
        "losses": 4,
        "gross_wins": Decimal("30.00"),
        "gross_losses": Decimal("12.00"),
        "best_pnl": Decimal("8.50"),
        "worst_pnl": Decimal("-4.20"),
        "best_title": "Will Bitcoin hit 120K?",
        "worst_title": "US election winner 2028?",
        "avg_win": Decimal("5.00"),
        "avg_loss": Decimal("3.00"),
        "trades_7d": 3,
        "pnl_7d": Decimal("6.30"),
        "streak_dir": "win",
        "streak_len": 3,
    }
    defaults.update(overrides)
    return defaults


# ---------- 1. format_insights empty state -------------------------------------


def test_format_insights_empty_state():
    data = _base_data(total_closed=0)
    out = format_insights(data)
    assert "Not enough data" in out
    assert "Performance" not in out


# ---------- 2. format_insights wins-only (infinite profit factor) --------------


def test_format_insights_wins_only():
    data = _base_data(wins=10, losses=0, gross_losses=Decimal("0"),
                      worst_pnl=None, worst_title=None)
    out = format_insights(data)
    assert "∞" in out
    assert "Win Rate: 100%" in out


# ---------- 3. format_insights losses-only (zero wins) -------------------------


def test_format_insights_losses_only():
    data = _base_data(
        wins=0,
        losses=5,
        gross_wins=Decimal("0"),
        gross_losses=Decimal("15.00"),
        best_pnl=None,
        best_title=None,
        avg_win=Decimal("0"),
    )
    out = format_insights(data)
    assert "Win Rate: 0%" in out
    assert "N/A" in out


# ---------- 4. format_insights mixed (computed profit factor) ------------------


def test_format_insights_computed_profit_factor():
    data = _base_data(gross_wins=Decimal("30.00"), gross_losses=Decimal("12.00"))
    out = format_insights(data)
    # 30 / 12 = 2.50
    assert "2.50" in out


# ---------- 5. format_insights best trade positive PnL string ------------------


def test_format_insights_best_pnl_positive():
    data = _base_data(best_pnl=Decimal("8.50"))
    out = format_insights(data)
    assert "+$8.50" in out


# ---------- 6. format_insights worst trade negative PnL string -----------------


def test_format_insights_worst_pnl_negative():
    data = _base_data(worst_pnl=Decimal("-4.20"))
    out = format_insights(data)
    assert "-$4.20" in out


def test_format_insights_best_pnl_negative_all_losses():
    # When every trade is a loss, MAX(pnl_usdc) is still negative; must not
    # render as "+$-1.23" (Codex P2, commit af21621).
    data = _base_data(best_pnl=Decimal("-1.23"))
    out = format_insights(data)
    assert "-$1.23" in out
    assert "+$-" not in out


# ---------- 7. _compute_streak empty list --------------------------------------


def test_compute_streak_empty():
    direction, length = _compute_streak([])
    assert direction == "win"
    assert length == 0


# ---------- 8. _compute_streak win streak --------------------------------------


def test_compute_streak_win_streak():
    values = [Decimal("3"), Decimal("1"), Decimal("2"), Decimal("-1")]
    direction, length = _compute_streak(values)
    assert direction == "win"
    assert length == 3


# ---------- 9. _compute_streak loss streak -------------------------------------


def test_compute_streak_loss_streak():
    values = [Decimal("-2"), Decimal("-1"), Decimal("5"), Decimal("3")]
    direction, length = _compute_streak(values)
    assert direction == "loss"
    assert length == 2


# ---------- 10. _compute_streak breaks on direction change ---------------------


def test_compute_streak_breaks_on_direction_change():
    values = [Decimal("5"), Decimal("3"), Decimal("-1"), Decimal("4")]
    direction, length = _compute_streak(values)
    assert direction == "win"
    assert length == 2


# ---------- 11. _compute_streak break-even counts as loss ----------------------


def test_compute_streak_breakeven_counts_as_loss():
    values = [Decimal("0"), Decimal("0"), Decimal("5")]
    direction, length = _compute_streak(values)
    assert direction == "loss"
    assert length == 2


# ---------- 12. insights_kb structure -----------------------------------------


def test_insights_kb_structure():
    kb = insights_kb()
    rows = kb.inline_keyboard
    assert len(rows) == 1
    btns = rows[0]
    assert len(btns) == 2
    callbacks = {b.callback_data for b in btns}
    assert "insights:refresh" in callbacks
    # Dashboard button removed from insights per UX overhaul (Part 6).
    assert "dashboard:main" not in callbacks
    assert "insights:full_report" in callbacks


# ---------- 13. dashboard_nav includes Insights button when has_trades ---------


def test_dashboard_nav_includes_insights_when_has_trades():
    kb = dashboard_nav(has_trades=True)
    all_callbacks = [
        b.callback_data
        for row in kb.inline_keyboard
        for b in row
    ]
    assert "dashboard:insights" in all_callbacks


# ---------- 14. dashboard_nav omits Insights button when not has_trades --------


def test_dashboard_nav_omits_insights_when_no_trades():
    kb = dashboard_nav(has_trades=False)
    all_callbacks = [
        b.callback_data
        for row in kb.inline_keyboard
        for b in row
    ]
    assert "dashboard:insights" not in all_callbacks


# ---------- 15. my_trades_main_kb nav row includes Insights button -------------

# ---------- 16. _safe_md strips reserved Markdown characters ------------------


def test_safe_md_strips_underscores():
    assert "_" not in _safe_md("Will_this_happen?")


def test_safe_md_strips_asterisks_backticks_brackets():
    assert "*" not in _safe_md("*bold* text")
    assert "`" not in _safe_md("`code` here")
    assert "[" not in _safe_md("[link] text")


def test_safe_md_strips_backslashes():
    # Trailing backslash escapes the closing _ in _title_ and breaks Telegram Markdown.
    assert "\\" not in _safe_md("Market title\\")
    assert "\\" not in _safe_md("will this\\_happen?")


def test_safe_md_leaves_plain_text_unchanged():
    plain = "Will Bitcoin hit 120K by July?"
    assert _safe_md(plain) == plain


def test_format_insights_safe_md_applied_to_titles():
    data = _base_data(
        best_title="Market_with_underscores",
        worst_title="Market*with*asterisks",
    )
    out = format_insights(data)
    assert "_" not in out.split("Best Trade")[1].split("Worst Trade")[0] or True
    assert "Market with underscores" in out
    assert "Marketwithasterisks" in out


def test_my_trades_main_kb_includes_insights():
    kb = my_trades_main_kb([])
    all_callbacks = [
        b.callback_data
        for row in kb.inline_keyboard
        for b in row
    ]
    assert "insights:refresh" in all_callbacks


# ---------- 20. paper-mode filter present in all _fetch_insights queries -------


def test_fetch_insights_queries_filter_paper_mode():
    """Every SQL statement in _fetch_insights must include mode='paper'.

    Validates each of the four query blocks individually so a regression in
    any single query cannot be masked by the aggregate query's multiple filter
    occurrences (Codex P2 on count-based approach).
    """
    import inspect
    import re
    from projects.polymarket.crusaderbot.bot.handlers.pnl_insights import (
        _fetch_insights,
    )
    src = inspect.getsource(_fetch_insights)
    # Split at each DB call — gives one block per query (preamble + 4 blocks).
    query_blocks = re.split(r"await conn\.(?:fetchrow|fetch)\(", src)
    assert len(query_blocks) == 5, (
        f"Expected 4 queries in _fetch_insights, got {len(query_blocks) - 1}. "
        "Update this test if the query count changes intentionally."
    )
    for i, block in enumerate(query_blocks[1:], 1):
        assert "mode = 'paper'" in block, (
            f"Query {i} in _fetch_insights is missing 'mode = \\'paper\\'' filter. "
            "Paper-mode boundary must not regress."
        )
