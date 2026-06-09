"""MVP dashboard status — bot must read 'Running' from auto_trade_on (not the
phantom 'auto_trade_enabled' key, which made the dashboard always show Stopped)."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from projects.polymarket.crusaderbot.bot.handlers.mvp import dashboard as dash


def _read(user_row):
    uid = uuid4()
    user_row = {"id": uid, **user_row}
    with patch.object(dash._users, "fetch_user", AsyncMock(return_value=user_row)), \
         patch.object(dash._users, "fetch_settings", AsyncMock(return_value={"active_preset": "close_sweep"})), \
         patch.object(dash._users, "fetch_balance", AsyncMock(return_value=1000.0)), \
         patch.object(dash._users, "fetch_daily_pnl", AsyncMock(return_value=0.0)), \
         patch.object(dash._users, "fetch_today_trade_count", AsyncMock(return_value=0)), \
         patch.object(dash._users, "fetch_open_position_count", AsyncMock(return_value=0)):
        tg_user = SimpleNamespace(id=12345, username="walk3r69")
        return asyncio.run(dash._read_dashboard(tg_user))


def test_dashboard_running_when_auto_trade_on():
    d = _read({"auto_trade_on": True, "paused": False})
    assert d["running"] is True


def test_dashboard_stopped_when_auto_trade_off():
    d = _read({"auto_trade_on": False, "paused": False})
    assert d["running"] is False


def test_dashboard_not_running_when_paused():
    d = _read({"auto_trade_on": True, "paused": True})
    assert d["running"] is False
