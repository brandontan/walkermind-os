from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..execution.engine import ExecutionEngine


def render_performance(engine: ExecutionEngine) -> str:
    """Generate performance summary for Telegram."""
    analytics = engine.get_analytics()
    summary = analytics.summary()
    return (
        "📊 Performance\n"
        f"├─ Trades       : {summary['trades']}\n"
        f"├─ Win Rate     : {summary['win_rate']:.0%}\n"
        f"├─ Avg PnL      : {summary['avg_pnl']:+.2%}\n"
        f"└─ Drawdown     : {summary['max_drawdown']:.2%}"
    )