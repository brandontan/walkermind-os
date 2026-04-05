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


def _as_float(value: Any) -> float | None:
    """Convert mixed numeric-like values to float when possible."""
    try:
        return float(str(value).replace("%", "").replace("$", "").replace(",", "").strip())
    except (AttributeError, TypeError, ValueError):
        return None


def generate_insight(data: Mapping[str, Any]) -> str:
    """Generate smart UI insight with risk-aware precedence."""
    raw_positions = data.get("positions", data.get("open_positions", 0))
    positions_value = _as_float(raw_positions)
    positions = int(positions_value) if positions_value is not None else 0

    if positions <= 0:
        return "Market inactive • Waiting edge"

    drawdown_value = _as_float(data.get("drawdown"))
    if drawdown_value is not None and drawdown_value > 0:
        return "Drawdown active • Risk control engaged"

    exposure_candidates = (
        data.get("ratio"),
        data.get("exposure_ratio"),
        data.get("exposure_pct"),
        data.get("exposure_percent"),
    )
    for value in exposure_candidates:
        exposure = _as_float(value)
        if exposure is None:
            continue
        if exposure > 1:
            exposure = exposure / 100
        if exposure >= 0.3:
            return "Risk elevated • Exposure high"

    if positions == 1:
        return "Position open • Monitoring outcome"

    return "Positions active • Monitoring outcome"
