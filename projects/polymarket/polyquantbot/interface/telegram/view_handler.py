"""Telegram view adapters for premium UI rendering."""

from __future__ import annotations

from typing import Any, Mapping

from ..ui_formatter import render_dashboard


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _base_payload(mode: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    positions = _as_list(payload.get("positions"))
    return {
        "state": payload.get("status", "waiting"),
        "mode": mode,
        "cycle": payload.get("cycle", "active"),
        "equity": payload.get("equity", 0),
        "positions": payload.get("positions_count", len(positions)),
        "exposure": payload.get("exposure", 0),
        "pnl": payload.get("pnl", payload.get("unrealized_pnl", 0)),
        "drawdown": payload.get("drawdown", 0),
        "risk_level": payload.get("risk_level", "standard"),
        "risk_state": payload.get("risk_state", "within limits"),
        "trend": payload.get("trend", "neutral"),
        "edge": payload.get("edge", 0),
        "edge_label": payload.get("edge_label"),
        "insight": payload.get("insight"),
        "confidence": payload.get("confidence", 0),
        "decision": payload.get("decision"),
        "operator_note": payload.get("operator_note"),
    }


async def render_view(name: str, payload: Mapping[str, Any]) -> str:
    action = str(name or "home").strip().lower()
    safe_payload: Mapping[str, Any] = payload or {}

    if action == "trade":
        dashboard_payload = _base_payload("trade", safe_payload)
        dashboard_payload.update(
            {
                "market_id": safe_payload.get("market_id", safe_payload.get("market")),
                "side": safe_payload.get("side", safe_payload.get("direction", "flat")),
                "entry": safe_payload.get("entry", safe_payload.get("entry_price", 0)),
                "size": safe_payload.get("size", safe_payload.get("allocation", 0)),
                "decision": safe_payload.get("decision", "deploy setup if risk gate clears"),
                "operator_note": safe_payload.get("operator_note", "review edge and liquidity before send"),
                "insight": safe_payload.get("insight", "signal is live and monitored"),
            }
        )
        return await render_dashboard(dashboard_payload)

    if action == "wallet":
        dashboard_payload = _base_payload("wallet", safe_payload)
        dashboard_payload.update(
            {
                "decision": safe_payload.get("decision", "capital preserved — no forced deployment"),
                "operator_note": safe_payload.get("operator_note", "wallet view is informational"),
                "insight": safe_payload.get("insight", "liquidity and collateral snapshot"),
                "positions": safe_payload.get("positions_count", len(_as_list(safe_payload.get("open_positions")))),
            }
        )
        return await render_dashboard(dashboard_payload)

    if action == "performance":
        dashboard_payload = _base_payload("performance", safe_payload)
        dashboard_payload.update(
            {
                "decision": safe_payload.get("decision", "optimize based on realized performance"),
                "operator_note": safe_payload.get("operator_note", "focus on drawdown and hit-rate trend"),
                "insight": safe_payload.get("insight", "performance metrics refreshed"),
            }
        )
        return await render_dashboard(dashboard_payload)

    if action in {"market", "markets"}:
        dashboard_payload = _base_payload("market", safe_payload)
        dashboard_payload.update(
            {
                "decision": safe_payload.get("decision", "scan for asymmetric opportunity"),
                "operator_note": safe_payload.get("operator_note", "rank by edge and confidence"),
                "insight": safe_payload.get("insight", "market context prioritized for execution"),
            }
        )
        return await render_dashboard(dashboard_payload)

    dashboard_payload = _base_payload("home", safe_payload)
    dashboard_payload.update(
        {
            "state": safe_payload.get("status", "running"),
            "decision": safe_payload.get("decision", "system healthy — await qualified signal"),
            "operator_note": safe_payload.get("operator_note", "monitor risk gates and telemetry"),
            "insight": safe_payload.get("insight", "home dashboard synchronized"),
        }
    )
    return await render_dashboard(dashboard_payload)
