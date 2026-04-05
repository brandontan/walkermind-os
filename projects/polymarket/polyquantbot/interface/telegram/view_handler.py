"""Telegram view adapters for premium UI rendering."""
from __future__ import annotations

from typing import Any, Mapping
from ..ui_formatter import render_dashboard


async def render_view(name: str, payload: Mapping[str, Any]) -> str:
    action = name.strip().lower()
    if action == "trade":
        return await render_dashboard(
            equity=payload.get("equity", 0),
            positions=len(payload.get("positions", [])),
            exposure=payload.get("exposure", 0),
            trend=payload.get("trend", "neutral"),
            edge=payload.get("edge", "low"),
            status=payload.get("status", "waiting"),
            market_id=payload.get("market_id"),
            side=payload.get("side"),
            entry_price=payload.get("entry_price"),
            size=payload.get("size"),
            pnl=payload.get("pnl"),
            exposure_safe=payload.get("exposure_safe", True),
            position_safe=payload.get("position_safe", True),
            drawdown=payload.get("drawdown", 0),
            decision=payload.get("decision", "waiting for opportunity"),
        )
    elif action == "wallet":
        return await render_dashboard(
            equity=payload.get("equity", 0),
            positions=0,
            exposure=0,
            trend="neutral",
            edge="low",
            status="waiting",
            decision="no active trades",
        )
    elif action == "performance":
        return await render_dashboard(
            equity=payload.get("equity", 0),
            positions=len(payload.get("positions", [])),
            exposure=payload.get("exposure", 0),
            trend=payload.get("trend", "neutral"),
            edge=payload.get("edge", "low"),
            status=payload.get("status", "waiting"),
            decision="performance review mode",
        )
    elif action in {"market", "markets"}:
        return await render_dashboard(
            equity=payload.get("equity", 0),
            positions=0,
            exposure=0,
            trend=payload.get("trend", "neutral"),
            edge=payload.get("edge", "low"),
            status=payload.get("status", "waiting"),
            decision="market analysis mode",
        )
    return await render_dashboard(
        equity=payload.get("equity", 0),
        positions=0,
        exposure=0,
        trend="neutral",
        edge="low",
        status="waiting",
        decision="home view",
    )
