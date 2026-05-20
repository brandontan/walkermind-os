"""Hermetic tests for dashboard_nav_cb routing — issue #1192.

Verifies that dashboard:portfolio routes to show_portfolio and
dashboard:trades routes to show_trades. No DB, no Telegram network calls.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


def _make_update(callback_data: str) -> SimpleNamespace:
    q = SimpleNamespace(
        data=callback_data,
        answer=AsyncMock(),
        message=SimpleNamespace(chat_id=1),
    )
    return SimpleNamespace(
        callback_query=q,
        effective_user=SimpleNamespace(id=1, username="test"),
        message=None,
    )


def _make_ctx() -> SimpleNamespace:
    return SimpleNamespace(user_data={}, bot=AsyncMock())


def test_dashboard_portfolio_routes_to_show_portfolio() -> None:
    """dashboard:portfolio must call show_portfolio, not show_trades."""
    update = _make_update("dashboard:portfolio")
    ctx = _make_ctx()

    show_portfolio_mock = AsyncMock()
    show_trades_mock = AsyncMock()

    with (
        patch(
            "projects.polymarket.crusaderbot.bot.handlers.dashboard.show_dashboard_for_cb",
            new=AsyncMock(),
        ),
        patch(
            "projects.polymarket.crusaderbot.bot.handlers.positions.show_portfolio",
            new=show_portfolio_mock,
            create=True,
        ),
        patch(
            "projects.polymarket.crusaderbot.bot.handlers.trades.show_trades",
            new=show_trades_mock,
            create=True,
        ),
    ):
        from projects.polymarket.crusaderbot.bot.handlers.dashboard import (
            dashboard_nav_cb,
        )

        asyncio.run(dashboard_nav_cb(update, ctx))

    show_portfolio_mock.assert_awaited_once_with(update, ctx)
    show_trades_mock.assert_not_awaited()


def test_dashboard_trades_routes_to_show_trades() -> None:
    """dashboard:trades must call show_trades."""
    update = _make_update("dashboard:trades")
    ctx = _make_ctx()

    show_portfolio_mock = AsyncMock()
    show_trades_mock = AsyncMock()

    with (
        patch(
            "projects.polymarket.crusaderbot.bot.handlers.dashboard.show_dashboard_for_cb",
            new=AsyncMock(),
        ),
        patch(
            "projects.polymarket.crusaderbot.bot.handlers.positions.show_portfolio",
            new=show_portfolio_mock,
            create=True,
        ),
        patch(
            "projects.polymarket.crusaderbot.bot.handlers.trades.show_trades",
            new=show_trades_mock,
            create=True,
        ),
    ):
        from projects.polymarket.crusaderbot.bot.handlers.dashboard import (
            dashboard_nav_cb,
        )

        asyncio.run(dashboard_nav_cb(update, ctx))

    show_trades_mock.assert_awaited_once_with(update, ctx)
    show_portfolio_mock.assert_not_awaited()
