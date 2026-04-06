"""Premium Telegram UI formatter for operator-grade summaries."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from projects.polymarket.polyquantbot.data.market_context import get_market_context

VIEW_TITLE = {
    "home": "🏠 Home Command",
    "wallet": "🧾 Wallet",
    "positions": "🎯 Position Monitor",
    "trade": "🎯 Position Monitor",
    "pnl": "💰 PnL",
    "performance": "📈 Performance",
    "exposure": "📊 Exposure",
    "risk": "⚠️ Risk",
    "strategy": "⚙️ Strategy",
    "market": "📡 Market",
    "markets": "📡 Market",
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


def _compact_text(value: object, default: str = "N/A", max_len: int = 72) -> str:
    text = _safe_text(value, default)
    return text if len(text) <= max_len else f"{text[: max_len - 1]}…"


def _fmt_currency(value: object) -> str:
    return f"${_safe_float(value):,.2f}"


def _fmt_signed_currency(value: object) -> str:
    return f"{_safe_float(value):+,.2f}"


def _fmt_percent(value: object, *, already_percent: bool = False) -> str:
    numeric = _safe_float(value)
    if not already_percent:
        numeric *= 100
    return f"{numeric:.1f}%"


def _fmt_signed_percent(value: object, *, already_percent: bool = False) -> str:
    numeric = _safe_float(value)
    if not already_percent:
        numeric *= 100
    return f"{numeric:+.1f}%"


def _fmt_probability_cents(value: object) -> str:
    numeric = _safe_float(value)
    cents = numeric * 100 if numeric <= 1.0 else numeric
    return f"{cents:.2f}¢"


def _format_opened_time(value: object) -> str:
    if value in (None, ""):
        return "Unknown"

    if isinstance(value, datetime):
        dt_value = value.astimezone(timezone.utc)
    else:
        text = str(value).strip()
        if not text:
            return "Unknown"
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt_value = datetime.fromisoformat(text)
        except ValueError:
            return _compact_text(value, "Unknown", max_len=24)
        if dt_value.tzinfo is None:
            dt_value = dt_value.replace(tzinfo=timezone.utc)
        dt_value = dt_value.astimezone(timezone.utc)

    return f"{dt_value.strftime('%b')} {dt_value.day}, {dt_value.strftime('%H:%M')} UTC"


def _direction(value: object) -> str:
    side = _safe_text(value, "FLAT").upper()
    if side in {"BUY", "LONG", "YES"}:
        return "🟢 YES"
    if side in {"SELL", "SHORT", "NO"}:
        return "🔴 NO"
    return f"🟡 {side}"


def _tree(label: str, value: object) -> str:
    return f"|-> {label}: {value}"


def _section(title: str, lines: list[str]) -> str:
    return "\n".join([title, *lines])


def _resolve_market_label(payload: Mapping[str, Any], context: Mapping[str, Any]) -> str:
    for candidate in (
        payload.get("market_title"),
        payload.get("market_name"),
        payload.get("market_question"),
        context.get("name"),
        context.get("question"),
        payload.get("market"),
    ):
        text = _compact_text(candidate, "", max_len=86)
        if text:
            return text

    market_id = _safe_text(payload.get("market_id"), "")
    if market_id:
        return f"Market {market_id[:12]}"
    return "Untitled market"


def _hero_block(mode: str, payload: Mapping[str, Any]) -> str:
    status = _safe_text(payload.get("state"), "waiting").upper()
    decision = _compact_text(payload.get("decision"), "Await qualified signal", max_len=84)
    risk_state = _compact_text(payload.get("risk_state"), "within limits", max_len=56)
    return _section(
        VIEW_TITLE.get(mode, VIEW_TITLE["home"]),
        [
            _tree("Status", status),
            _tree("Now", decision),
            _tree("Risk", risk_state),
        ],
    )


def _primary_block(mode: str, payload: Mapping[str, Any]) -> str:
    personalities: dict[str, tuple[str, list[str]]] = {
        "home": (
            "📊 Portfolio",
            [
                _tree("Equity", _fmt_currency(payload.get("equity"))),
                _tree("Exposure", _fmt_percent(payload.get("exposure"))),
                _tree("Open Positions", _safe_int(payload.get("positions"))),
            ],
        ),
        "wallet": (
            "🧾 Wallet",
            [
                _tree("Equity", _fmt_currency(payload.get("equity"))),
                _tree("Available", _fmt_currency(payload.get("available_balance", payload.get("equity")))),
                _tree("Unrealized", _fmt_signed_currency(payload.get("pnl"))),
            ],
        ),
        "positions": (
            "🎯 Position Monitor",
            [
                _tree("Open Positions", _safe_int(payload.get("positions"))),
                _tree("Exposure", _fmt_percent(payload.get("exposure"))),
                _tree("Confidence", _fmt_percent(payload.get("confidence"), already_percent=True)),
            ],
        ),
        "pnl": (
            "💰 PnL",
            [
                _tree("Unrealized", _fmt_signed_currency(payload.get("pnl"))),
                _tree("Realized", _fmt_signed_currency(payload.get("realized_pnl"))),
                _tree("Drawdown", _fmt_percent(payload.get("drawdown"))),
            ],
        ),
        "performance": (
            "📈 Performance",
            [
                _tree("Net PnL", _fmt_signed_currency(payload.get("pnl"))),
                _tree("Drawdown", _fmt_percent(payload.get("drawdown"))),
                _tree("Confidence", _fmt_percent(payload.get("confidence"), already_percent=True)),
            ],
        ),
        "exposure": (
            "📊 Exposure",
            [
                _tree("Portfolio Exposure", _fmt_percent(payload.get("exposure"))),
                _tree("Open Positions", _safe_int(payload.get("positions"))),
                _tree("Risk Tier", _safe_text(payload.get("risk_level"), "standard")),
            ],
        ),
        "risk": (
            "⚠️ Risk",
            [
                _tree("Risk Tier", _safe_text(payload.get("risk_level"), "standard")),
                _tree("Limit State", _safe_text(payload.get("risk_state"), "within limits")),
                _tree("Drawdown", _fmt_percent(payload.get("drawdown"))),
            ],
        ),
        "strategy": (
            "⚙️ Strategy",
            [
                _tree("Mode", _safe_text(payload.get("strategy_mode"), "default")),
                _tree("Signal", _safe_text(payload.get("signal_state"), "monitoring")),
                _tree("Activation", _safe_text(payload.get("state"), "active")),
            ],
        ),
        "market": (
            "📡 Market",
            [
                _tree("Regime", _safe_text(payload.get("trend"), "neutral")),
                _tree("Edge", _safe_text(payload.get("edge_label"), _fmt_signed_percent(payload.get("edge")))),
                _tree("Context", "Risk 0.25 · Max Pos 0.10"),
            ],
        ),
    }
    title, lines = personalities.get(mode, personalities["home"])
    return _section(title, lines)


def _render_position_card(payload: Mapping[str, Any], market_label: str) -> str:
    if not (payload.get("market_id") or payload.get("market_title") or payload.get("entry") or payload.get("size")):
        return ""

    now_value = payload.get("current") if payload.get("current") is not None else payload.get("entry")
    lines = [
        _tree("Market", market_label),
        _tree("Side", _direction(payload.get("side"))),
        _tree("Entry", _fmt_probability_cents(payload.get("entry"))),
        _tree("Now", _fmt_probability_cents(now_value)),
        _tree("Size", _fmt_currency(payload.get("size"))),
        _tree("UPNL", _fmt_signed_currency(payload.get("pnl"))),
        _tree("Opened", _format_opened_time(payload.get("opened_at"))),
        _tree("Status", _safe_text(payload.get("position_status"), "Monitoring")),
    ]
    market_id = _safe_text(payload.get("market_id"), "")
    if market_id:
        lines.append(_tree("Ref", market_id[:18]))
    return _section("🎯 Position", lines)


def _render_market_card(payload: Mapping[str, Any], market_label: str) -> str:
    lines = [
        _tree("Title", market_label),
        _tree("Regime", _safe_text(payload.get("trend"), "neutral")),
        _tree("Edge", _safe_text(payload.get("edge_label"), _fmt_signed_percent(payload.get("edge")))),
        _tree("Summary", _compact_text(payload.get("insight"), "Monitoring market context", max_len=84)),
    ]
    if payload.get("market_id"):
        lines.append(_tree("Ref", _safe_text(payload.get("market_id"))))
    return _section("📡 Market", lines)


def _render_operator_note(payload: Mapping[str, Any]) -> str:
    note = _compact_text(payload.get("operator_note"), "Monitoring with current safeguards.", max_len=100)
    return _section("🧠 Operator Note", [_tree("Note", note)])


async def render_position(
    market_id: object,
    side: object,
    entry: object,
    size: object,
    pnl: object,
    confidence: object,
    edge: object,
    *,
    current: object = None,
    opened_at: object = None,
    market_title: object = None,
) -> str:
    context = await get_market_context(_safe_text(market_id, "")) or {}
    market_label = _resolve_market_label(
        {"market_id": market_id, "market_title": market_title},
        context,
    )
    payload = {
        "market_id": market_id,
        "market_title": market_title,
        "side": side,
        "entry": entry,
        "size": size,
        "pnl": pnl,
        "confidence": confidence,
        "edge": edge,
        "current": current,
        "opened_at": opened_at,
    }
    return _render_position_card(payload, market_label)


async def render_dashboard(payload: Mapping[str, Any]) -> str:
    """Premium dashboard entry point with emoji hierarchy and tree readability."""
    normalized: dict[str, Any] = dict(payload or {})
    mode = _safe_text(normalized.get("mode"), "home").lower()

    context = await get_market_context(_safe_text(normalized.get("market_id"), "")) or {}
    market_label = _resolve_market_label(normalized, context)

    blocks: list[str] = [
        _hero_block(mode, normalized),
        _primary_block(mode, normalized),
    ]

    position_card = _render_position_card(normalized, market_label)
    if position_card:
        blocks.append(position_card)

    blocks.append(_render_market_card(normalized, market_label))
    blocks.append(_render_operator_note(normalized))

    return "\n\n".join(blocks)
