"""WARP-93 (Issue 4): the legacy copy_trade scan skips orchestrator-managed
preset users so a stale strategy_types array cannot bleed copy_trade scans onto
a candle_auto (Smart Strike) user.

Hermetic — no network, no DB (pool/conn + strategy mocked).
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from projects.polymarket.crusaderbot import scheduler


def _ctx(value=None):
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=value)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _pool(conn):
    p = MagicMock()
    p.acquire = MagicMock(return_value=_ctx(conn))
    return p


def _user(active_preset, strategy_types):
    return {
        "id": "00000000-0000-0000-0000-000000000001",
        "telegram_user_id": 123,
        "role": "user",
        "auto_trade_on": True,
        "paused": False,
        "balance_usdc": 1000.0,
        "active_preset": active_preset,
        "strategy_types": strategy_types,
        "risk_profile": "balanced",
        "trading_mode": "paper",
        "daily_loss_override": None,
        "tp_pct": None,
        "sl_pct": None,
    }


def _run_scan(rows):
    scanned_for: list = []

    class _FakeStrat:
        async def scan(self, market_filters, user_context):
            scanned_for.append(str(user_context["id"]))
            return []  # no candidates -> no execution path

    conn = MagicMock()
    conn.fetch = AsyncMock(return_value=rows)
    fake_settings = MagicMock(ENABLE_LIVE_TRADING=False)
    with patch.object(scheduler, "get_pool", return_value=_pool(conn)), \
         patch.object(scheduler, "_resolve_mode", return_value="paper"), \
         patch.object(scheduler, "get_settings", return_value=fake_settings), \
         patch.dict(scheduler._strategies, {"copy_trade": _FakeStrat()}, clear=True):
        asyncio.run(scheduler.run_signal_scan())
    return scanned_for


def test_candle_auto_user_skipped_by_legacy_scan():
    """A candle_auto user with a stale 'copy_trade' strategy_types must NOT be
    scanned by the legacy copy_trade path."""
    rows = [_user("candle_auto", ["copy_trade", "signal", "value"])]
    assert _run_scan(rows) == []


def test_all_managed_presets_skipped():
    rows = [
        _user("candle_auto", ["copy_trade"]),
        _user("close_sweep", ["copy_trade"]),
        _user("safe_close", ["copy_trade"]),
        _user("flip_hunter", ["copy_trade"]),
        _user("weather_monitor", ["copy_trade"]),
        _user("playbook", ["copy_trade"]),
    ]
    assert _run_scan(rows) == []


def test_preset_less_copy_trade_user_still_scanned():
    """Pre-preset legacy copy_trade users (active_preset NULL) keep working."""
    rows = [_user(None, ["copy_trade"])]
    assert _run_scan(rows) == ["00000000-0000-0000-0000-000000000001"]
