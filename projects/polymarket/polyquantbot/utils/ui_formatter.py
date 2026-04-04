"""UI formatter helpers for Telegram premium architecture views.

Views are intentionally separated to avoid duplicated data:
- HOME: system + strategy + intelligence only
- PORTFOLIO: position-level data only
- WALLET: financial balances only
- PERFORMANCE: performance metrics only
"""
from __future__ import annotations

from typing import Any, Mapping


def _value(data: Mapping[str, Any], key: str, default: str = "N/A") -> str:
    """Return a safe string value for formatting."""
    raw = data.get(key, default)
    if raw is None:
        return default
    return str(raw)


def build_home(data: Mapping[str, Any]) -> str:
    """Build HOME dashboard with system-only architecture sections."""
    return f"""
╔════════════════════════════╗
   🚀 KRUSADER v2.0 — AI TRADER
╚════════════════════════════╝

⚙️ SYSTEM
├ STATUS     {_value(data, "status")}
├ MODE       {_value(data, "mode")}
├ MARKETS    {_value(data, "markets")}
└ LATENCY    {_value(data, "latency")}

🧠 STRATEGY
└ ENGINE     {_value(data, "strategy")}

📡 INTELLIGENCE
├ SCAN       {_value(data, "scan")}
└ DISTRIB    {_value(data, "distribution")}

━━━━━━━━━━━━━━━━━━━━━━
💡 {_value(data, "insight")}
""".strip()


def build_portfolio(data: Mapping[str, Any]) -> str:
    """Build PORTFOLIO view with position details only."""
    return f"""
💼 PORTFOLIO
├ POSITIONS  {_value(data, "positions")}
├ EXPOSURE   {_value(data, "exposure")}
├ SIDE       {_value(data, "side")}
└ RISK       {_value(data, "risk")}

📌 ACTIVE POSITION
├ MARKET     {_value(data, "market")}
├ ENTRY      {_value(data, "entry")}
├ SIZE       {_value(data, "size")}
└ PNL        {_value(data, "pnl")}
""".strip()


def build_wallet(data: Mapping[str, Any]) -> str:
    """Build WALLET view with financial balances only."""
    return f"""
💰 WALLET
├ BALANCE    {_value(data, "balance")}
├ EQUITY     {_value(data, "equity")}
├ USED       {_value(data, "used")}
├ FREE       {_value(data, "free")}
└ MARGIN     {_value(data, "margin")}
""".strip()


def build_performance(data: Mapping[str, Any]) -> str:
    """Build PERFORMANCE view with PnL and hit-rate metrics only."""
    return f"""
📊 PERFORMANCE
├ REALIZED   {_value(data, "realized")}
├ UNREAL     {_value(data, "unreal")}
├ WR         {_value(data, "wr")}
└ PF         {_value(data, "pf")}
""".strip()
