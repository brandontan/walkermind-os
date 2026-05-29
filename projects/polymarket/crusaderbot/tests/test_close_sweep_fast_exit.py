"""PR #2 — close_sweep force-exit ~8s before resolution + scoped fast loop."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from projects.polymarket.crusaderbot.domain.positions import registry
from projects.polymarket.crusaderbot import scheduler


def _ctx(value=None):
    cm = MagicMock(); cm.__aenter__ = AsyncMock(return_value=value); cm.__aexit__ = AsyncMock(return_value=False); return cm

def _pool(conn):
    p = MagicMock(); p.acquire = MagicMock(return_value=_ctx(conn)); return p


def test_scoped_query_filters_candle_presets_and_near_window():
    """list_open_candle_positions_for_exit must scope by candle presets +
    a near-resolution window, and bind both params."""
    conn = MagicMock()
    captured = {}

    async def fetch(query, *args):
        captured["query"] = query
        captured["args"] = args
        return []

    conn.fetch = fetch
    with patch.object(registry, "get_pool", return_value=_pool(conn)):
        asyncio.run(registry.list_open_candle_positions_for_exit(90))

    q = captured["query"]
    assert "active_preset = ANY($1::text[])" in q
    assert "resolution_at <= NOW() + make_interval(secs => $2)" in q
    assert "m.resolved = FALSE" in q
    assert captured["args"][0] == list(registry._CANDLE_PRESETS)
    assert captured["args"][1] == 90


def test_candle_presets_constant():
    assert set(registry._CANDLE_PRESETS) == {"close_sweep", "safe_close", "flip_hunter"}


def test_check_candle_exits_scopes_loader_and_skips_resolved():
    """The scheduler driver calls run_once with the scoped loader + Phase B off."""
    seen = {}

    async def fake_run_once(*, position_loader=None, run_resolved_phase=True, **kw):
        seen["has_loader"] = position_loader is not None
        seen["run_resolved_phase"] = run_resolved_phase
        return scheduler.exit_watcher.RunResult(submitted=0, expired=0, held=0, errors=0)

    fake_settings = MagicMock(CLOSE_SWEEP_EXIT_NEAR_SEC=90)
    with patch.object(scheduler.exit_watcher, "run_once", fake_run_once), \
         patch.object(scheduler, "get_settings", return_value=fake_settings):
        out = asyncio.run(scheduler.check_candle_exits())
    assert seen["has_loader"] is True
    assert seen["run_resolved_phase"] is False
    assert out == {"submitted": 0, "expired": 0, "held": 0, "errors": 0}
