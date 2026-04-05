"""Shared product-grade formatting helpers for Telegram interface views."""
from __future__ import annotations

from typing import Any, Mapping

SEPARATOR = "━━━━━━━━━━━━━━━"


def fmt(value: Any) -> str:
    """Normalize missing/empty values to UI placeholder."""
    if value is None:
        return "—"
    if isinstance(value, str):
        text = value.strip()
        if not text or text.upper() == "N/A":
            return "—"
        return text
    if isinstance(value, float):
        return f"{value:,.2f}" if value % 1 else f"{int(value):,}"
    return str(value)


def pnl(value: Any) -> str:
    """Render signed PnL values; zero must be +0.00."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{number:+,.2f}"


def block(value: Any, label: str) -> str:
    """Render value-first block for premium product layout."""
    return f"{fmt(value)}\n{label}"


def generate_insight(data: Mapping[str, Any]) -> str:
    """Generate a concise AI insight across all UI views."""
    raw_positions = data.get("positions", data.get("open_positions", 0))
    try:
        positions = int(float(raw_positions))
    except (TypeError, ValueError):
        positions = 0

    if positions <= 0:
        return "No active trades • Waiting signal"

    drawdown = data.get("drawdown")
    if drawdown not in (None, "", "—"):
        try:
            drawdown_value = float(drawdown)
        except (TypeError, ValueError):
            drawdown_value = 0.0
        if abs(drawdown_value) > 0:
            return "Drawdown detected • Risk active"

    low_exposure = False
    exposure_candidates = [
        data.get("ratio"),
        data.get("exposure_ratio"),
        data.get("exposure"),
        data.get("total_exposure"),
        data.get("unrealized"),
    ]
    for value in exposure_candidates:
        try:
            numeric = abs(float(value))
        except (TypeError, ValueError):
            continue
        if numeric <= 0.3:
            low_exposure = True
            break

    if low_exposure:
        return "Low exposure • Safe positioning"

    return "Monitoring positions"
