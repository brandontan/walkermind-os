"""Telegram view adapters for premium UI rendering."""
from __future__ import annotations

from typing import Any, Mapping
from ..ui_formatter import render_dashboard


async def render_view(name: str, payload: Mapping[str, Any]) -> str:
    action = name.strip().lower()
    if action == "trade":
        return await render_dashboard(
            {
                "state": payload.get("status", "waiting"),
                "mode": "trade",
                "equity": payload.get("equity", 0),
                "positions": len(payload.get("positions", [])),
                "exposure": payload.get("exposure", 0),
                "market_id": payload.get("market_id"),
                "side": payload.get("side"),
                "entry": payload.get("entry", payload.get("entry_price")),
                "size": payload.get("size"),
                "pnl": payload.get("pnl"),
                "drawdown": payload.get("drawdown", 0),
                "insight": (
                    f"trend={payload.get('trend', 'neutral')} | "
                    f"edge={payload.get('edge', 'low')}"
                ),
                "decision": payload.get("decision", "waiting for opportunity"),
            }
        )
    elif action == "wallet":
        return await render_dashboard(
            {
                "state": "waiting",
                "mode": "wallet",
                "equity": payload.get("equity", 0),
                "positions": 0,
                "exposure": 0,
                "drawdown": payload.get("drawdown", 0),
                "insight": "wallet snapshot",
                "decision": "no active trades",
            }
        )
    elif action == "performance":
        return await render_dashboard(
            {
                "state": payload.get("status", "waiting"),
                "mode": "performance",
                "equity": payload.get("equity", 0),
                "positions": len(payload.get("positions", [])),
                "exposure": payload.get("exposure", 0),
                "drawdown": payload.get("drawdown", 0),
                "insight": (
                    f"trend={payload.get('trend', 'neutral')} | "
                    f"edge={payload.get('edge', 'low')}"
                ),
                "decision": "performance review mode",
            }
        )
    elif action in {"market", "markets"}:
        return await render_dashboard(
            {
                "state": payload.get("status", "waiting"),
                "mode": "market",
                "equity": payload.get("equity", 0),
                "positions": 0,
                "exposure": 0,
                "drawdown": payload.get("drawdown", 0),
                "insight": (
                    f"trend={payload.get('trend', 'neutral')} | "
                    f"edge={payload.get('edge', 'low')}"
                ),
                "decision": "market analysis mode",
            }
        )
    return await render_dashboard(
        {
            "state": "waiting",
            "mode": "home",
            "equity": payload.get("equity", 0),
            "positions": 0,
            "exposure": 0,
            "drawdown": payload.get("drawdown", 0),
            "insight": "home overview",
            "decision": "home view",
        }
    )
