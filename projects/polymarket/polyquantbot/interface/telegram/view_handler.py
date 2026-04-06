"""Telegram view adapters for premium UI rendering."""

from __future__ import annotations

from typing import Any, Mapping

from ..ui_formatter import render_dashboard

_ACTION_ALIAS: dict[str, str] = {
    "start": "home",
    "menu": "home",
    "main_menu": "home",
    "dashboard": "home",
    "status": "system",
    "position": "positions",
    "summary": "refresh",
    "settings_notify": "notifications",
    "settings_auto": "auto_trade",
    "settings_mode": "mode",
    "settings_risk": "risk",
}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _first_present(payload: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in payload and payload.get(key) not in (None, ""):
            return payload.get(key)
    return default


def _base_payload(mode: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    positions = _as_list(payload.get("positions"))
    markets = _as_list(payload.get("markets"))
    return {
        "state": payload.get("status", "waiting"),
        "mode": mode,
        "cycle": payload.get("cycle", "active"),
        "equity": payload.get("equity", payload.get("balance", 0)),
        "positions": payload.get("positions_count", len(positions)),
        "exposure": payload.get("exposure", 0),
        "pnl": payload.get("pnl", payload.get("unrealized_pnl", 0)),
        "realized_pnl": payload.get("realized_pnl", 0),
        "drawdown": payload.get("drawdown", 0),
        "risk_level": payload.get("risk_level", "standard"),
        "risk_state": payload.get("risk_state", "within limits"),
        "trend": payload.get("trend", "neutral"),
        "edge": payload.get("edge", 0),
        "edge_label": payload.get("edge_label"),
        "available_balance": payload.get("available_balance", payload.get("free_balance", payload.get("equity", payload.get("balance", 0)))),
        "insight": payload.get("insight"),
        "confidence": payload.get("confidence", 0),
        "decision": payload.get("decision"),
        "operator_note": payload.get("operator_note"),
        "market_title": _first_present(payload, "market_title", "market_name", "question"),
        "market_question": payload.get("question"),
        "market_id": _first_present(payload, "market_id", "market"),
        "current": _first_present(payload, "current", "current_price", "last_price"),
        "side": payload.get("side", payload.get("direction", "flat")),
        "entry": payload.get("entry", payload.get("entry_price", 0)),
        "size": payload.get("size", payload.get("allocation", 0)),
        "opened_at": _first_present(payload, "opened_at", "opened", "opened_time", "created_at"),
        "strategy_mode": payload.get("strategy_mode"),
        "signal_state": payload.get("signal_state"),
        "markets_total": payload.get("markets_total", payload.get("total_markets", len(markets))),
        "markets_active": payload.get("markets_active", payload.get("active_markets", 0)),
        "updated_at": _first_present(payload, "updated_at", "last_updated", "timestamp", "time"),
        "mode_label": _first_present(payload, "mode_label", "mode", default="PAPER"),
        "target_mode": payload.get("target_mode"),
        "mode_guard": payload.get("mode_guard"),
        "auto_trade_state": payload.get("auto_trade_state", "manual"),
        "critical_alerts": payload.get("critical_alerts", "enabled"),
        "trade_alerts": payload.get("trade_alerts", "enabled"),
        "summary_alerts": payload.get("summary_alerts", "hourly"),
        "control_action": payload.get("control_action", "standby"),
    }


async def render_view(name: str, payload: Mapping[str, Any]) -> str:
    raw_action = str(name or "home").strip().lower()
    action = _ACTION_ALIAS.get(raw_action, raw_action)
    safe_payload: Mapping[str, Any] = payload or {}

    if action == "trade":
        dashboard_payload = _base_payload("trade", safe_payload)
        dashboard_payload.update(
            {
                "mode": "trade",
                "side": safe_payload.get("side", safe_payload.get("direction", "flat")),
                "entry": safe_payload.get("entry", safe_payload.get("entry_price", 0)),
                "size": safe_payload.get("size", safe_payload.get("allocation", 0)),
                "decision": safe_payload.get("decision", "Deploy only if edge + liquidity both qualify"),
                "operator_note": safe_payload.get("operator_note", "Review slippage and depth before send"),
                "insight": safe_payload.get("insight", "One-glance card highlights side, price, and risk posture"),
            }
        )
        return await render_dashboard(dashboard_payload)

    if action == "wallet":
        dashboard_payload = _base_payload("wallet", safe_payload)
        dashboard_payload.update(
            {
                "decision": safe_payload.get("decision", "Capital intact — deployment is optional"),
                "operator_note": safe_payload.get("operator_note", "Account summary only; no execution implied"),
                "insight": safe_payload.get("insight", "Wallet summary prioritizes capital readiness"),
                "positions": safe_payload.get("positions_count", len(_as_list(safe_payload.get("open_positions")))),
            }
        )
        return await render_dashboard(dashboard_payload)

    if action in {"positions", "position"}:
        dashboard_payload = _base_payload("positions", safe_payload)
        dashboard_payload.update(
            {
                "side": safe_payload.get("side", safe_payload.get("direction", "flat")),
                "entry": safe_payload.get("entry", safe_payload.get("entry_price", 0)),
                "size": safe_payload.get("size", safe_payload.get("allocation", 0)),
                "decision": safe_payload.get("decision", "Monitor active positions; protect downside"),
                "operator_note": safe_payload.get("operator_note", "Prioritize drawdown and concentration risks"),
                "insight": safe_payload.get("insight", "Active risk and side exposure are visible first"),
            }
        )
        return await render_dashboard(dashboard_payload)

    if action == "pnl":
        dashboard_payload = _base_payload("pnl", safe_payload)
        dashboard_payload.update(
            {
                "decision": safe_payload.get("decision", "Track realized vs unrealized before scaling"),
                "operator_note": safe_payload.get("operator_note", "Evaluate losses before new entries"),
                "insight": safe_payload.get("insight", "Cash impact is grouped for rapid operator scan"),
            }
        )
        return await render_dashboard(dashboard_payload)

    if action == "performance":
        dashboard_payload = _base_payload("performance", safe_payload)
        dashboard_payload.update(
            {
                "decision": safe_payload.get("decision", "Optimize based on rolling scorecard"),
                "operator_note": safe_payload.get("operator_note", "Keep drawdown stable while compounding edge"),
                "insight": safe_payload.get("insight", "Scorecard emphasizes trend stability"),
            }
        )
        return await render_dashboard(dashboard_payload)

    if action == "exposure":
        dashboard_payload = _base_payload("exposure", safe_payload)
        dashboard_payload.update(
            {
                "decision": safe_payload.get("decision", "Rebalance if concentration exceeds comfort"),
                "operator_note": safe_payload.get("operator_note", "Exposure view tracks concentration pressure"),
                "insight": safe_payload.get("insight", "Concentration pressure is shown before action"),
            }
        )
        return await render_dashboard(dashboard_payload)

    if action == "risk":
        dashboard_payload = _base_payload("risk", safe_payload)
        dashboard_payload.update(
            {
                "decision": safe_payload.get("decision", "Risk preset active — respect hard limits"),
                "operator_note": safe_payload.get("operator_note", "Escalate when drawdown or liquidity warnings fire"),
                "insight": safe_payload.get("insight", "Risk consequences are shown in plain language"),
            }
        )
        return await render_dashboard(dashboard_payload)

    if action == "strategy":
        dashboard_payload = _base_payload("strategy", safe_payload)
        dashboard_payload.update(
            {
                "decision": safe_payload.get("decision", "Strategy toggles define eligibility for execution"),
                "operator_note": safe_payload.get("operator_note", "Confirm activation state after each config change"),
                "insight": safe_payload.get("insight", "Activation gates are explicit for operator control"),
            }
        )
        return await render_dashboard(dashboard_payload)

    if action in {"market", "markets"}:
        mode = "markets" if action == "markets" else "market"
        dashboard_payload = _base_payload(mode, safe_payload)
        dashboard_payload.update(
            {
                "decision": safe_payload.get("decision", "Scan for asymmetric opportunity"),
                "operator_note": safe_payload.get("operator_note", "Use market context before committing capital"),
                "insight": safe_payload.get("insight", "Market title-first rendering keeps ids secondary"),
            }
        )
        return await render_dashboard(dashboard_payload)

    if action in {"refresh", "summary"}:
        dashboard_payload = _base_payload("refresh", safe_payload)
        dashboard_payload.update(
            {
                "decision": safe_payload.get("decision", "Snapshot refreshed — review posture before next action"),
                "operator_note": safe_payload.get("operator_note", "Refresh confirms current state only; execution remains gated"),
                "insight": safe_payload.get("insight", "Refresh summary keeps operators aligned with latest values"),
            }
        )
        return await render_dashboard(dashboard_payload)

    if action == "system":
        dashboard_payload = _base_payload("system", safe_payload)
        dashboard_payload.update(
            {
                "decision": safe_payload.get("decision", "System state synchronized across menu paths"),
                "operator_note": safe_payload.get("operator_note", "Use status menu tabs for detailed operational views"),
                "insight": safe_payload.get("insight", "System summary stays isolated from trade-specific cards"),
            }
        )
        return await render_dashboard(dashboard_payload)

    if action == "settings":
        dashboard_payload = _base_payload("settings", safe_payload)
        dashboard_payload.update(
            {
                "decision": safe_payload.get("decision", "Adjust runtime preferences with guardrails enabled"),
                "operator_note": safe_payload.get("operator_note", "Settings menus now follow the same renderer grammar"),
                "insight": safe_payload.get("insight", "Configuration context is isolated from market and position cards"),
            }
        )
        return await render_dashboard(dashboard_payload)

    if action == "notifications":
        dashboard_payload = _base_payload("notifications", safe_payload)
        dashboard_payload.update(
            {
                "decision": safe_payload.get("decision", "Notification delivery profile ready"),
                "operator_note": safe_payload.get("operator_note", "Critical alerts remain always on"),
                "insight": safe_payload.get("insight", "Alert settings are grouped in one consistent card style"),
            }
        )
        return await render_dashboard(dashboard_payload)

    if action == "auto_trade":
        dashboard_payload = _base_payload("auto_trade", safe_payload)
        dashboard_payload.update(
            {
                "decision": safe_payload.get("decision", "Enable only after confirming risk and mode settings"),
                "operator_note": safe_payload.get("operator_note", "Auto-trade changes execution automation, not risk limits"),
                "insight": safe_payload.get("insight", "Automation state is explicit and isolated from market cards"),
            }
        )
        return await render_dashboard(dashboard_payload)

    if action == "mode":
        dashboard_payload = _base_payload("mode", safe_payload)
        dashboard_payload.update(
            {
                "decision": safe_payload.get("decision", "Review target mode and environment guard before switching"),
                "operator_note": safe_payload.get("operator_note", "Mode confirmation should match runtime safety flags"),
                "insight": safe_payload.get("insight", "Mode transition details are rendered consistently for callbacks and commands"),
            }
        )
        return await render_dashboard(dashboard_payload)

    if action == "control":
        dashboard_payload = _base_payload("control", safe_payload)
        dashboard_payload.update(
            {
                "decision": safe_payload.get("decision", "Control actions are available with kill-switch safeguards"),
                "operator_note": safe_payload.get("operator_note", "Pause, resume, and stop remain explicit operator actions"),
                "insight": safe_payload.get("insight", "Control menu is isolated from unrelated market and position cards"),
            }
        )
        return await render_dashboard(dashboard_payload)

    dashboard_payload = _base_payload("home", safe_payload)
    dashboard_payload.update(
        {
            "state": safe_payload.get("status", "running"),
            "decision": safe_payload.get("decision", "System healthy — await qualified signal"),
            "operator_note": safe_payload.get("operator_note", "Command center synced across major views"),
            "insight": safe_payload.get("insight", "Command center highlights immediate posture"),
        }
    )
    return await render_dashboard(dashboard_payload)
