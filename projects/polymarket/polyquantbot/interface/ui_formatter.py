"""Premium Telegram UI formatter for operator-grade summaries."""

from __future__ import annotations

from typing import Any, Mapping

from projects.polymarket.polyquantbot.data.market_context import get_market_context

SECTION_DIVIDER = "────────────────────"

EMOJI = {
    "system": "🧭",
    "portfolio": "💼",
    "risk": "🛡️",
    "decision": "🎯",
    "market": "🌐",
    "trade": "📌",
}


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _safe_text(value: object, default: str = "N/A") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _fmt_currency(value: object) -> str:
    return f"${_safe_float(value):,.2f}"


def _fmt_percent(value: object, *, already_percent: bool = False) -> str:
    numeric = _safe_float(value)
    if already_percent:
        return f"{numeric:.1f}%"
    return f"{numeric * 100:.1f}%"


def _fmt_signed_percent(value: object, *, already_percent: bool = False) -> str:
    numeric = _safe_float(value)
    if not already_percent:
        numeric *= 100
    return f"{numeric:+.1f}%"


def _fmt_signed_currency(value: object) -> str:
    numeric = _safe_float(value)
    return f"{numeric:+,.2f}"


def _direction(value: object) -> str:
    side = _safe_text(value, "FLAT").upper()
    if side in {"BUY", "LONG", "YES"}:
        return f"🟢 {side}"
    if side in {"SELL", "SHORT", "NO"}:
        return f"🔴 {side}"
    return f"🟡 {side}"


def _line(label: str, value: object) -> str:
    return f"• {label}: {value}"


def _section(title: str, lines: list[str]) -> str:
    return "\n".join([SECTION_DIVIDER, title, *lines])


async def render_position(
    market_id: object,
    side: object,
    entry: object,
    size: object,
    pnl: object,
    confidence: object,
    edge: object,
) -> str:
    context = await get_market_context(_safe_text(market_id, "")) or {}
    market_name = _safe_text(context.get("name") or context.get("question") or market_id)

    lines = [
        _line("Market", market_name),
        _line("Direction", _direction(side)),
        _line("Entry", _fmt_currency(entry)),
        _line("Sizing", _fmt_currency(size)),
        _line("Edge", _fmt_signed_percent(edge)),
        _line("Confidence", _fmt_percent(confidence, already_percent=True)),
        _line("Open PnL", _fmt_signed_currency(pnl)),
    ]
    return _section(f"{EMOJI['trade']} TRADE", lines)


def _render_system(payload: Mapping[str, Any]) -> str:
    lines = [
        _line("Status", _safe_text(payload.get("state"), "waiting")),
        _line("View", _safe_text(payload.get("mode"), "home")),
        _line("Cycle", _safe_text(payload.get("cycle"), "active")),
    ]
    return _section(f"{EMOJI['system']} SYSTEM", lines)


def _render_portfolio(payload: Mapping[str, Any]) -> str:
    lines = [
        _line("Equity", _fmt_currency(payload.get("equity"))),
        _line("Open Positions", _safe_int(payload.get("positions"))),
        _line("Exposure", _fmt_percent(payload.get("exposure"))),
        _line("Unrealized PnL", _fmt_signed_currency(payload.get("pnl"))),
    ]
    return _section(f"{EMOJI['portfolio']} PORTFOLIO", lines)


def _render_risk(payload: Mapping[str, Any]) -> str:
    lines = [
        _line("Drawdown", _fmt_percent(payload.get("drawdown"))),
        _line("Risk Tier", _safe_text(payload.get("risk_level"), "standard")),
        _line("Limit State", _safe_text(payload.get("risk_state"), "within limits")),
    ]
    return _section(f"{EMOJI['risk']} RISK", lines)


def _render_decision(payload: Mapping[str, Any]) -> str:
    action = _safe_text(payload.get("decision"), "wait for qualified setup")
    confidence = _fmt_percent(payload.get("confidence", 0.0), already_percent=True)
    lines = [
        _line("Action", action),
        _line("Confidence", confidence),
        _line("Operator Note", _safe_text(payload.get("operator_note"), "execution ready")),
    ]
    return _section(f"{EMOJI['decision']} DECISION", lines)


def _render_market_context(payload: Mapping[str, Any]) -> str:
    lines = [
        _line("Regime", _safe_text(payload.get("trend"), "neutral")),
        _line("Signal Edge", _safe_text(payload.get("edge_label"), _fmt_signed_percent(payload.get("edge")))),
        _line("Narrative", _safe_text(payload.get("insight"), "monitoring flow")),
    ]
    return _section(f"{EMOJI['market']} MARKET CONTEXT", lines)


async def render_dashboard(payload: Mapping[str, Any]) -> str:
    """Premium dashboard entry point with safe defaults."""
    normalized: dict[str, Any] = dict(payload or {})

    blocks: list[str] = [
        _render_system(normalized),
        _render_portfolio(normalized),
    ]

    mode = _safe_text(normalized.get("mode"), "home").lower()
    has_trade = bool(normalized.get("market_id")) or mode == "trade"
    if has_trade:
        blocks.append(
            await render_position(
                normalized.get("market_id"),
                normalized.get("side"),
                normalized.get("entry"),
                normalized.get("size"),
                normalized.get("pnl"),
                normalized.get("confidence"),
                normalized.get("edge"),
            )
        )

    blocks.extend(
        [
            _render_risk(normalized),
            _render_decision(normalized),
            _render_market_context(normalized),
        ]
    )

    return "\n\n".join(blocks)
