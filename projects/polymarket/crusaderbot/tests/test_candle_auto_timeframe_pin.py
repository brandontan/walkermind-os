"""WARP-93 (Issue 2): activate_preset pins candle_auto (Smart Strike) to 5m.

The web UI timeframe toggle can persist a stale '15m' and re-POST it on a later
preset activation. candle_auto is the orchestrator-owned auto-router and LIVE v1
trades the 5m crypto cells only (the Polymarket updown-15m series is
discontinued — 15m == zero trades), so the single write path must coerce
candle_auto to 5m regardless of the client value. The single-rule crypto-short
presets keep their toggle.

Hermetic — no network, no DB (pool/conn mocked).
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from projects.polymarket.crusaderbot.webtrader.backend import router as r
from projects.polymarket.crusaderbot.webtrader.backend.schemas import (
    PresetActivateRequest,
)


def _ctx(value=None):
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=value)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _pool(conn):
    p = MagicMock()
    p.acquire = MagicMock(return_value=_ctx(conn))
    return p


def _run_activate(preset_key: str, requested_tf):
    """Drive activate_preset, capturing the persisted timeframe ($2)."""
    conn = MagicMock()
    captured: dict = {}

    async def execute(query, *args):
        captured["query"] = query
        captured["args"] = args
        return "UPDATE 1"

    conn.execute = execute
    body = PresetActivateRequest(
        preset_key=preset_key,
        selected_timeframe=requested_tf,
        selected_assets=["BTC", "ETH", "SOL"],
    )
    user = {"user_id": "11111111-1111-1111-1111-111111111111"}
    with patch.object(r, "get_pool", return_value=_pool(conn)):
        out = asyncio.run(r.activate_preset(body, user))
    return out, captured


def test_candle_auto_15m_request_pinned_to_5m():
    """A stale '15m' from the client must NOT strand a candle_auto user."""
    out, captured = _run_activate("candle_auto", "15m")
    # $1 = preset_key, $2 = persisted selected_timeframe
    assert captured["args"][0] == "candle_auto"
    assert captured["args"][1] == "5m"
    assert out["selected_timeframe"] == "5m"


def test_candle_auto_none_request_defaults_5m():
    out, captured = _run_activate("candle_auto", None)
    assert captured["args"][1] == "5m"
    assert out["selected_timeframe"] == "5m"


def test_candle_auto_5m_request_stays_5m():
    out, captured = _run_activate("candle_auto", "5m")
    assert captured["args"][1] == "5m"
    assert out["selected_timeframe"] == "5m"


def test_single_rule_preset_keeps_15m_toggle():
    """The pin is candle_auto-only: close_sweep can still pick 15m."""
    out, captured = _run_activate("close_sweep", "15m")
    assert captured["args"][0] == "close_sweep"
    assert captured["args"][1] == "15m"
    assert out["selected_timeframe"] == "15m"
