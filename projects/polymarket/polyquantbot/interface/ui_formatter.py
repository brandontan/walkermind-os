"""Premium Telegram UI formatter for operator-grade summaries."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from projects.polymarket.polyquantbot.data.market_context import get_market_context

SECTION_DIVIDER = "────────────────────"

EMOJI = {
    "home": "🧭",
    "wallet": "💼",
    "positions": "📌",
    "pnl": "📈",
    "performance": "🏁",
    "exposure": "🧩",
    "risk": "🛡️",
    "strategy": "🎛️",
    "market": "🌐",
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
    numeric = _safe_float(value)
    return f"{numeric:+,.2f}"


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

    month = dt_value.strftime("%b")
    day = dt_value.day
    return f"{month} {day}, {dt_value.strftime('%H:%M')} UTC"


def _direction(value: object) -> str:
    side = _safe_text(value, "FLAT").upper()
    if side in {"BUY", "LONG", "YES"}:
        return "🟢 YES"
    if side in {"SELL", "SHORT", "NO"}:
        return "🔴 NO"
    return f"🟡 {side}"


def _line(label: str, value: object) -> str:
    return f"• {label}: {value}"


def _meta_line(label: str, value: object) -> str:
    return f"◦ {label}: {value}"


def _section(title: str, lines: list[str]) -> str:
    return "\n".join([SECTION_DIVIDER, title, *lines])


def _resolve_market_label(payload: Mapping[str, Any], context: Mapping[str, Any]) -> str:
    for candidate in (
        payload.get("market_title"),
        payload.get("market_question"),
        context.get("name"),
        context.get("question"),
        payload.get("market"),
    ):
        text = _compact_text(candidate, "", max_len=86)
        if text and text != "":
            return text
    market_id = _safe_text(payload.get("market_id"), "Unknown market")
    return f"Market {market_id[:16]}"


def _hero_block(mode: str, payload: Mapping[str, Any], market_label: str) -> str:
    status = _safe_text(payload.get("state"), "waiting").upper()
    decision = _compact_text(payload.get("decision"), "Await qualified setup")
    icon = EMOJI.get(mode, EMOJI["home"])

    hero_lines = [
        f"{icon} {mode.upper()} COMMAND",
        f"Status: {status}",
        f"Now: {decision}",
    ]

    if payload.get("market_id") or payload.get("market"):
        hero_lines.append(f"Market: {market_label}")

    return "\n".join(hero_lines)


def _primary_state(mode: str, payload: Mapping[str, Any]) -> str:
    mode_map: dict[str, tuple[str, list[str]]] = {
        "home": (
            "PRIMARY STATE",
            [
                _line("Cycle", _safe_text(payload.get("cycle"), "active")),
                _line("Open Positions", _safe_int(payload.get("positions"))),
                _line("Risk State", _safe_text(payload.get("risk_state"), "within limits")),
            ],
        ),
        "wallet": (
            "ACCOUNT SNAPSHOT",
            [
                _line("Equity", _fmt_currency(payload.get("equity"))),
                _line("Unrealized", _fmt_signed_currency(payload.get("pnl"))),
                _line("Exposure", _fmt_percent(payload.get("exposure"))),
            ],
        ),
        "positions": (
            "POSITION MONITOR",
            [
                _line("Open Positions", _safe_int(payload.get("positions"))),
                _line("Exposure", _fmt_percent(payload.get("exposure"))),
                _line("Confidence", _fmt_percent(payload.get("confidence"), already_percent=True)),
            ],
        ),
        "pnl": (
            "PNL SUMMARY",
            [
                _line("Unrealized", _fmt_signed_currency(payload.get("pnl"))),
                _line("Realized", _fmt_signed_currency(payload.get("realized_pnl"))),
                _line("Drawdown", _fmt_percent(payload.get("drawdown"))),
            ],
        ),
        "performance": (
            "SCORECARD",
            [
                _line("PnL", _fmt_signed_currency(payload.get("pnl"))),
                _line("Drawdown", _fmt_percent(payload.get("drawdown"))),
                _line("Confidence", _fmt_percent(payload.get("confidence"), already_percent=True)),
            ],
        ),
        "exposure": (
            "ALLOCATION VIEW",
            [
                _line("Exposure", _fmt_percent(payload.get("exposure"))),
                _line("Open Positions", _safe_int(payload.get("positions"))),
                _line("Risk Tier", _safe_text(payload.get("risk_level"), "standard")),
            ],
        ),
        "risk": (
            "RISK PRESET",
            [
                _line("Risk Tier", _safe_text(payload.get("risk_level"), "standard")),
                _line("Limit State", _safe_text(payload.get("risk_state"), "within limits")),
                _line("Drawdown", _fmt_percent(payload.get("drawdown"))),
            ],
        ),
        "strategy": (
            "STRATEGY STATE",
            [
                _line("Mode", _safe_text(payload.get("strategy_mode"), "default")),
                _line("Signal", _safe_text(payload.get("signal_state"), "monitoring")),
                _line("Decision", _compact_text(payload.get("decision"), "Await qualified setup", 56)),
            ],
        ),
    }

    title, lines = mode_map.get(mode, mode_map["home"])
    return _section(title, lines)


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
        {
            "market_title": market_title,
            "market_id": market_id,
        },
        context,
    )

    now_value = current if current is not None else entry
    lines = [
        _line("Market", market_label),
        _line("Side", _direction(side)),
        _line("Entry", _fmt_probability_cents(entry)),
        _line("Now", _fmt_probability_cents(now_value)),
        _line("Size", _fmt_currency(size)),
        _line("UPNL", _fmt_signed_currency(pnl)),
        _line("Opened", _format_opened_time(opened_at)),
        _meta_line("Edge", _fmt_signed_percent(edge)),
        _meta_line("Confidence", _fmt_percent(confidence, already_percent=True)),
        _meta_line("Insight", "Healthy" if _safe_float(pnl) >= 0 else "Needs attention"),
    ]

    raw_id = _safe_text(market_id, "N/A")
    lines.append(_meta_line("Market ID", raw_id))
    return _section("ACTIVE POSITION", lines)


def _render_market_context(payload: Mapping[str, Any], market_label: str) -> str:
    lines = [
        _line("Market", market_label),
        _line("Regime", _safe_text(payload.get("trend"), "neutral")),
        _line("Signal Edge", _safe_text(payload.get("edge_label"), _fmt_signed_percent(payload.get("edge")))),
        _line("Narrative", _compact_text(payload.get("insight"), "Monitoring flow")),
    ]
    if payload.get("market_id"):
        lines.append(_meta_line("Ref", _safe_text(payload.get("market_id"))))
    return _section("MARKET CONTEXT", lines)


def _render_metrics(payload: Mapping[str, Any]) -> str:
    lines = [
        _line("Equity", _fmt_currency(payload.get("equity"))),
        _line("Exposure", _fmt_percent(payload.get("exposure"))),
        _line("Unrealized", _fmt_signed_currency(payload.get("pnl"))),
        _line("Drawdown", _fmt_percent(payload.get("drawdown"))),
    ]
    return _section("KEY METRICS", lines)


def _render_operator_note(payload: Mapping[str, Any]) -> str:
    note = _compact_text(payload.get("operator_note"), "No operator note.", max_len=120)
    return _section("OPERATOR NOTE", [f"• {note}"])


async def render_dashboard(payload: Mapping[str, Any]) -> str:
    """Premium dashboard entry point with safe defaults and view personality."""
    normalized: dict[str, Any] = dict(payload or {})
    mode = _safe_text(normalized.get("mode"), "home").lower()

    context = await get_market_context(_safe_text(normalized.get("market_id"), "")) or {}
    market_label = _resolve_market_label(normalized, context)

    blocks: list[str] = [
        _hero_block(mode, normalized, market_label),
        _primary_state(mode, normalized),
        _render_metrics(normalized),
    ]

    has_position = bool(normalized.get("market_id")) or mode in {"trade", "positions"}
    if has_position:
        blocks.append(
            await render_position(
                normalized.get("market_id"),
                normalized.get("side"),
                normalized.get("entry"),
                normalized.get("size"),
                normalized.get("pnl"),
                normalized.get("confidence"),
                normalized.get("edge"),
                current=normalized.get("current", normalized.get("current_price")),
                opened_at=normalized.get("opened_at"),
                market_title=normalized.get("market_title") or normalized.get("market_question"),
            )
        )

    blocks.extend(
        [
            _render_market_context(normalized, market_label),
            _render_operator_note(normalized),
        ]
    )

    return "\n\n".join(blocks)
