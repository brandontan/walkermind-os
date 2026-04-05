"""PERFORMANCE premium dashboard view."""
from __future__ import annotations

from typing import Any, Mapping

from .helpers import SEPARATOR, block, pnl


TITLE = "📈 PERFORMANCE"
SUBTITLE = "Polymarket AI Trader"


def _to_pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "—"


def _performance_insight(total_pnl: Any, trades: Any) -> str:
    try:
        trade_count = int(float(trades))
    except (TypeError, ValueError):
        trade_count = 0

    signed = pnl(total_pnl)
    if trade_count == 0:
        return "No active trades • Waiting signal"
    if signed.startswith("+"):
        return "Low exposure • Safe positioning"
    return "1 position open • Monitoring" if trade_count == 1 else f"{trade_count} positions open • Monitoring"


def render_performance_view(data: Mapping[str, Any]) -> str:
    total_pnl = data.get("total_pnl", data.get("pnl", 0.0))
    trades = data.get("trades", data.get("total_trades"))
    sections = [
        f"{TITLE}\n{SUBTITLE}",
        block("Total PnL", pnl(total_pnl), "Total PnL"),
        block("Win Rate", _to_pct(data.get("winrate", data.get("wr"))), "Win Rate"),
        block("Trades", trades, "Completed Trades"),
        block("Drawdown", _to_pct(data.get("drawdown")), "Drawdown"),
        f"🧠 Insight\n{_performance_insight(total_pnl, trades)}",
    ]
    return f"\n{SEPARATOR}\n".join(sections)
