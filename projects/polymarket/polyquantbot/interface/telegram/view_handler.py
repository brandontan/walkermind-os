"""Telegram view adapters for premium UI rendering."""
from __future__ import annotations

from typing import Any, Mapping

from ..ui.views import (
    render_exposure_view,
    render_home_view,
    render_performance_view,
    render_risk_view,
    render_strategy_view,
    render_wallet_view,
)


def render_view(name: str, payload: Mapping[str, Any]) -> str:
    key = name.strip().lower()
    if key == "home":
        return render_home_view(payload)
    if key == "wallet":
        return render_wallet_view(payload)
    if key == "performance":
        return render_performance_view(payload)
    if key in {"exposure", "portfolio"}:
        return render_exposure_view(payload)
    if key in {"strategy", "strategies"}:
        return render_strategy_view(payload)
    if key == "risk":
        return render_risk_view(payload)
    return render_home_view(payload)
