"""Shared premium formatting helpers for Telegram interface views."""
from __future__ import annotations

from typing import Any

SEPARATOR = "━━━━━━━━━━━━━━━"


def fmt(value: Any) -> str:
    """Normalize missing/empty values to a premium placeholder."""
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


def row(label: str, value: Any) -> str:
    """Render one compact aligned label/value row."""
    return f"{label:<10} {fmt(value)}"


def pnl(value: Any) -> str:
    """Render signed PnL values; zero must be +0.00."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{number:+,.2f}"
