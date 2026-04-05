"""PERFORMANCE premium dashboard view."""
from __future__ import annotations

from typing import Any, Mapping

from .helpers import SEPARATOR, pnl, row


def _to_pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "—"


def render_performance_view(data: Mapping[str, Any]) -> str:
    total_pnl = data.get("total_pnl", data.get("pnl", 0.0))
    win_rate = data.get("winrate", data.get("wr"))
    insight = "Positive expectancy maintained." if pnl(total_pnl).startswith("+") else "Stabilize signals before scaling risk."

    lines = [
        "📈 PERFORMANCE",
        row("Total PnL", pnl(total_pnl)),
        row("Win Rate", _to_pct(win_rate)),
        row("Trades", data.get("trades", data.get("total_trades"))),
        SEPARATOR,
        row("Drawdown", _to_pct(data.get("drawdown"))),
        SEPARATOR,
        f"🧠 Insight  {insight}",
    ]
    return "\n".join(lines)
