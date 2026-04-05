"""Telegram view adapters for premium UI rendering."""
from __future__ import annotations

from typing import Any, Mapping

from ..ui.views import (
    render_exposure_view,
    render_home_view,
    render_market_view,
    render_performance_view,
    render_positions_view,
    render_risk_view,
    render_strategy_view,
    render_wallet_view,
)


def render_view(name: str, payload: Mapping[str, Any]) -> str:
    action = name.strip().lower()
    if action == "trade":
        return render_positions_view(payload)
    elif action == "wallet":
        return render_wallet_view(payload)
    elif action == "performance":
        return render_performance_view(payload)
    elif action == "exposure":
        return render_exposure_view(payload)
    elif action == "strategy":
        return render_strategy_view(payload)
    elif action == "home":
        return render_home_view(payload)
    elif action == "positions":
        return render_positions_view(payload)
    elif action == "portfolio":
        return render_exposure_view(payload)
    elif action == "strategies":
        return render_strategy_view(payload)
    elif action == "risk":
        return render_risk_view(payload)
    elif action in {"market", "markets"}:
        return render_market_view(payload)
    return render_home_view(payload)
