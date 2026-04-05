"""HOME elite premium dashboard view."""
from __future__ import annotations

from typing import Any, Mapping

from .helpers import SEPARATOR, block, generate_insight, pnl


TITLE = "🏠 HOME"
SUBTITLE = "Polymarket AI Trader"


def _to_float(value: Any) -> float | None:
    """Parse numeric-like values from mixed inputs."""
    try:
        return float(str(value).replace("%", "").replace("$", "").replace(",", "").strip())
    except (AttributeError, TypeError, ValueError):
        return None


def _fmt_money(value: Any) -> str:
    """Format values as compact currency for premium inline layout."""
    numeric = _to_float(value)
    if numeric is None:
        return "$0"
    return f"${numeric:,.0f}"


def _fmt_positions(value: Any) -> str:
    """Format open position count for compact portfolio block."""
    numeric = _to_float(value)
    if numeric is None:
        return "0 pos"
    return f"{int(numeric)} pos"


def _fmt_exposure_ratio(data: Mapping[str, Any]) -> str:
    """Format exposure ratio into percent text."""
    for key in ("ratio", "exposure_ratio", "exposure_pct", "exposure_percent"):
        numeric = _to_float(data.get(key))
        if numeric is None:
            continue
        if numeric > 1:
            return f"{numeric:.1f}%"
        return f"{numeric * 100:.1f}%"
    return "0.0%"


def _build_portfolio_line(data: Mapping[str, Any]) -> str:
    """Compose compressed portfolio summary line."""
    balance = _fmt_money(data.get("balance") or 0)
    equity = _fmt_money(data.get("equity") or data.get("net_worth") or 0)
    positions = _fmt_positions(data.get("positions") or data.get("open_positions") or 0)
    return f"{balance} • {equity} • {positions}"


def _build_exposure_line(data: Mapping[str, Any]) -> str:
    """Compose compact exposure line: percent and absolute value."""
    ratio = _fmt_exposure_ratio(data)
    exposure = _fmt_money(
        data.get("total_exposure")
        or data.get("exposure")
        or data.get("unrealized")
        or 0
    )
    return f"{ratio} • {exposure}"


def render_home_view(data: Mapping[str, Any]) -> str:
    hero_metric = block(pnl(data.get("total_pnl") or data.get("pnl") or 0.0), "Total PnL")
    portfolio = block(_build_portfolio_line(data), "Portfolio")
    exposure = block(_build_exposure_line(data), "Exposure")
    insight = f"🧠 Insight\n{generate_insight(data)}"
    return (
        f"{hero_metric}\n"
        f"{TITLE}\n{SUBTITLE}\n"
        f"{SEPARATOR}\n"
        f"{portfolio}\n"
        f"{exposure}\n"
        f"{SEPARATOR}\n"
        f"{insight}"
    )
