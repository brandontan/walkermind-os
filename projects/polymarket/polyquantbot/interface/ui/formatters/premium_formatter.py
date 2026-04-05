"""Unified premium formatter for Telegram UI hierarchy views."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Iterable, Mapping


def section(title: str) -> str:
    """Render a premium section header."""
    return f"━━━━━━━━━━━━━━\n{title}\n━━━━━━━━━━━━━━"


def item(label: str, value: Any) -> str:
    """Render a tree item with sibling connector."""
    return f"├─ {label:<12} {_safe_text(value)}"


def item_last(label: str, value: Any) -> str:
    """Render a tree item with terminal connector."""
    return f"└─ {label:<12} {_safe_text(value)}"


def block(lines: Iterable[str]) -> str:
    """Join lines into one display block."""
    return "\n".join(lines)


def divider() -> str:
    """Render premium divider line."""
    return "━━━━━━━━━━━━━━"


def _safe_text(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return "—"
        return "—" if text.replace("/", "").upper() == "NA" else text
    return str(value)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value).replace("$", "").replace(",", "").replace("%", "").strip())
    except (AttributeError, TypeError, ValueError):
        return default


def pnl_color(pnl: float) -> str:
    """Return emoji color marker for pnl direction."""
    if pnl > 0:
        return "🟢"
    if pnl < 0:
        return "🔴"
    return "⚪"


def format_pnl(value: Any) -> str:
    """Format pnl with directional emoji marker."""
    pnl = _to_float(value)
    return f"{pnl_color(pnl)} ${pnl:,.2f}"


def _market_obj_from_mapping(data: Mapping[str, Any]) -> Any:
    market_id = data.get("market_id") or data.get("id") or "—"
    title = data.get("market_title") or data.get("question") or data.get("title")
    if not title:
        title = "Unknown Market"
    return SimpleNamespace(
        id=market_id,
        title=title,
        category=data.get("market_category") or data.get("category") or "—",
    )


def format_market(market: Any) -> list[str]:
    """Render market context tree with truncation and safe fallback."""
    if isinstance(market, Mapping):
        market = _market_obj_from_mapping(market)

    market_id = getattr(market, "id", "—")
    title = getattr(market, "title", None)
    category = getattr(market, "category", "—")

    if not title:
        title = "Unknown Market"

    title_text = str(title)
    if len(title_text) > 40:
        title_text = title_text[:40] + "..."

    return [
        "🆔 Market",
        f"├─ ID        : {market_id}",
        f"├─ Title     : {title_text}",
        f"└─ Category  : {category}",
    ]


def format_position(position: Any, market: Any, index: int = 1) -> str:
    """Render one fully humanized position card."""
    side = getattr(position, "side", "NO")
    direction = "🟢 YES" if side == "YES" else "🔴 NO"
    entry_price = _to_float(getattr(position, "entry_price", getattr(position, "avg_price", 0.0)))
    current_price = _to_float(getattr(position, "current_price", entry_price))
    size = _to_float(getattr(position, "size", 0.0))
    pnl = _to_float(getattr(position, "pnl", getattr(position, "unrealized_pnl", 0.0)))

    lines: list[str] = []
    lines += [
        f"📊 POSITION #{index}",
        "━━━━━━━━━━━━━━",
    ]
    lines += format_market(market)
    lines += [
        "",
        "📍 Your Position",
        f"├─ Direction   : {direction}",
        f"├─ Entry Price : {entry_price:.4f}",
        f"├─ Current     : {current_price:.4f}",
        f"└─ Position Size ($): ${size:.0f}",
        "",
        "💰 Profit / Loss",
        f"└─ Unrealized  : {format_pnl(pnl)}",
        "",
        "🧠 Insight",
        "└─ Monitoring active position",
        "━━━━━━━━━━━━━━",
    ]
    return "\n".join(lines)


def format_count(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, tuple):
        return len(value)
    return int(_to_float(value, default=0.0))


def format_money(value: Any) -> str:
    return f"${_to_float(value):,.2f}"


def format_percent(value: Any) -> str:
    num = _to_float(value)
    if num > 1:
        return f"{num:.2f}%"
    return f"{num * 100:.2f}%"
