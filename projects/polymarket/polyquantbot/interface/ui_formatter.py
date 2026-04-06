"""Premium Telegram UI formatter for operator-grade summaries."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from projects.polymarket.polyquantbot.data.market_context import get_market_context

VIEW_TITLE = {
    "home": "🏠 Home Command",
    "system": "🧠 System Status",
    "wallet": "💼 Wallet Snapshot",
    "positions": "📈 Open Positions",
    "trade": "🎯 Trade Detail",
    "pnl": "💰 PnL",
    "performance": "📈 Performance",
    "exposure": "📊 Exposure",
    "risk": "⚠️ Risk",
    "strategy": "⚙️ Strategy",
    "market": "📡 Market",
    "markets": "🛰️ Markets",
    "refresh": "🔄 Refresh Summary",
    "settings": "⚙️ Settings",
    "notifications": "🔔 Notifications",
    "auto_trade": "🤖 Auto Trade",
    "mode": "🔀 Mode",
    "control": "🎛️ Control",
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


def _tree_group(items: list[tuple[str, object]]) -> list[str]:
    if not items:
        return []
    lines: list[str] = []
    last_index = len(items) - 1
    for idx, (label, value) in enumerate(items):
        branch = "└" if idx == last_index else "├"
        lines.append(f"{branch} {label}: {value}")
    return lines


def _section(title: str, lines: list[str]) -> str:
    return "\n".join([title, *lines])


def _resolve_market_label(payload: Mapping[str, Any], context: Mapping[str, Any]) -> str:
    def _is_generic_label(text: str) -> bool:
        compact = text.strip().lower()
        return compact in {"market", "market #", "untitled"} or compact.startswith("market #")

    for candidate in (
        payload.get("market_title"),
        payload.get("market_question"),
        payload.get("market_name"),
        context.get("question"),
        context.get("name"),
        payload.get("market"),
    ):
        text = _compact_text(candidate, "", max_len=86)
        if text and not _is_generic_label(text):
            return text

    market_id = _safe_text(payload.get("market_id"), "")
    if market_id:
        return f"Untitled market (ref {market_id[:12]})"
    return "Untitled market"


def _hero_block(mode: str, payload: Mapping[str, Any]) -> str:
    status = _safe_text(payload.get("state"), "waiting").upper()
    decision = _compact_text(payload.get("decision"), "Await qualified signal", max_len=84)
    risk_state = _compact_text(payload.get("risk_state"), "within limits", max_len=56)
    return _section(
        VIEW_TITLE.get(mode, VIEW_TITLE["home"]),
        _tree_group(
            [
                ("Status", status),
                ("Now", decision),
                ("Risk", risk_state),
            ]
        ),
    )


def _primary_block(mode: str, payload: Mapping[str, Any]) -> str:
    personalities: dict[str, tuple[str, list[tuple[str, object]]]] = {
        "home": (
            "📊 Portfolio",
            [
                ("Total Value", _fmt_currency(payload.get("equity"))),
                ("Exposure", _fmt_percent(payload.get("exposure"))),
                ("Open Positions", _safe_int(payload.get("positions"))),
            ],
        ),
        "system": (
            "🧠 Runtime",
            [
                ("State", _safe_text(payload.get("state"), "running").upper()),
                ("Risk State", _safe_text(payload.get("risk_state"), "within limits")),
                ("Cycle", _safe_text(payload.get("cycle"), "active")),
            ],
        ),
        "wallet": (
            "💰 Account",
            [
                ("Total Value", _fmt_currency(payload.get("equity"))),
                ("Available Balance", _fmt_currency(payload.get("available_balance", payload.get("equity")))),
                ("Unrealized", _fmt_signed_currency(payload.get("pnl"))),
            ],
        ),
        "positions": (
            "💼 Portfolio",
            [
                ("Total Value", _fmt_currency(payload.get("equity"))),
                ("PNL", _fmt_signed_currency(payload.get("pnl"))),
                ("Markets Traded", _safe_int(payload.get("positions"))),
            ],
        ),
        "trade": (
            "🧭 Trade Focus",
            [
                ("Status", _safe_text(payload.get("state"), "ready").upper()),
                ("Signal Confidence", _fmt_percent(payload.get("confidence"), already_percent=True)),
                ("Edge", _safe_text(payload.get("edge_label"), _fmt_signed_percent(payload.get("edge")))),
            ],
        ),
        "pnl": (
            "💰 PnL",
            [
                ("Unrealized", _fmt_signed_currency(payload.get("pnl"))),
                ("Realized", _fmt_signed_currency(payload.get("realized_pnl"))),
                ("Drawdown", _fmt_percent(payload.get("drawdown"))),
            ],
        ),
        "performance": (
            "🏁 Scorecard",
            [
                ("Net PnL", _fmt_signed_currency(payload.get("pnl"))),
                ("Drawdown", _fmt_percent(payload.get("drawdown"))),
                ("Confidence", _fmt_percent(payload.get("confidence"), already_percent=True)),
            ],
        ),
        "exposure": (
            "🧱 Concentration",
            [
                ("Portfolio Exposure", _fmt_percent(payload.get("exposure"))),
                ("Open Positions", _safe_int(payload.get("positions"))),
                ("Risk Tier", _safe_text(payload.get("risk_level"), "standard")),
            ],
        ),
        "risk": (
            "🛡️ Risk Preset",
            [
                ("Risk Tier", _safe_text(payload.get("risk_level"), "standard")),
                ("Limit State", _safe_text(payload.get("risk_state"), "within limits")),
                ("Drawdown", _fmt_percent(payload.get("drawdown"))),
            ],
        ),
        "strategy": (
            "🎛️ Activation",
            [
                ("Mode", _safe_text(payload.get("strategy_mode"), "default")),
                ("Signal", _safe_text(payload.get("signal_state"), "monitoring")),
                ("Activation", _safe_text(payload.get("state"), "active")),
            ],
        ),
        "market": (
            "📡 Market",
            [
                ("Regime", _safe_text(payload.get("trend"), "neutral")),
                ("Edge", _safe_text(payload.get("edge_label"), _fmt_signed_percent(payload.get("edge")))),
                ("Summary", "Risk 0.25 · Max Pos 0.10"),
            ],
        ),
        "markets": (
            "🗂️ Market Scan",
            [
                ("Scanned", _safe_int(payload.get("markets_total"))),
                ("Active", _safe_int(payload.get("markets_active"))),
                ("Focus", _compact_text(payload.get("decision"), "Scan for asymmetric opportunity", max_len=56)),
            ],
        ),
        "refresh": (
            "🔄 Snapshot",
            [
                ("State", _safe_text(payload.get("state"), "running").upper()),
                ("Open Positions", _safe_int(payload.get("positions"))),
                ("PNL", _fmt_signed_currency(payload.get("pnl"))),
            ],
        ),
        "settings": (
            "⚙️ Config Surface",
            [
                ("Risk Level", _safe_text(payload.get("risk_level"), "standard")),
                ("Mode", _safe_text(payload.get("mode_label"), "PAPER")),
                ("Auto Trade", _safe_text(payload.get("auto_trade_state"), "manual")),
            ],
        ),
        "notifications": (
            "🔔 Alerting",
            [
                ("Critical Alerts", _safe_text(payload.get("critical_alerts"), "enabled")),
                ("Trade Updates", _safe_text(payload.get("trade_alerts"), "enabled")),
                ("Summary", _safe_text(payload.get("summary_alerts"), "hourly")),
            ],
        ),
        "auto_trade": (
            "🤖 Execution Mode",
            [
                ("Mode", _safe_text(payload.get("mode_label"), "PAPER")),
                ("Auto Trade", _safe_text(payload.get("auto_trade_state"), "manual")),
                ("Risk Guard", "Kelly 0.25 · Max Pos 0.10"),
            ],
        ),
        "mode": (
            "🔀 Mode Switch",
            [
                ("Current", _safe_text(payload.get("mode_label"), "PAPER")),
                ("Target", _safe_text(payload.get("target_mode"), "N/A")),
                ("Guard", _safe_text(payload.get("mode_guard"), "Validated before switch")),
            ],
        ),
        "control": (
            "🎛️ System Control",
            [
                ("State", _safe_text(payload.get("state"), "running").upper()),
                ("Action", _safe_text(payload.get("control_action"), "standby")),
                ("Kill Switch", "Armed"),
            ],
        ),
    }
    title, lines = personalities.get(mode, personalities["home"])
    return _section(title, _tree_group(lines))


def _render_position_card(payload: Mapping[str, Any], market_label: str) -> str:
    if not (payload.get("market_id") or payload.get("market_title") or payload.get("entry") or payload.get("size")):
        return ""

    now_value = payload.get("current") if payload.get("current") is not None else payload.get("entry")
    lines = [
        ("Market", market_label),
        ("Side", _direction(payload.get("side"))),
        ("Entry", _fmt_probability_cents(payload.get("entry"))),
        ("Now", _fmt_probability_cents(now_value)),
        ("Size", _fmt_currency(payload.get("size"))),
        ("UPNL", _fmt_signed_currency(payload.get("pnl"))),
        ("Opened", _format_opened_time(payload.get("opened_at"))),
        ("Status", _safe_text(payload.get("position_status"), "Monitoring")),
    ]
    market_id = _safe_text(payload.get("market_id"), "")
    if market_id:
        lines.append(("Ref", market_id[:18]))
    return _section("🎯 Position", _tree_group(lines))


def _render_market_card(payload: Mapping[str, Any], market_label: str) -> str:
    lines: list[tuple[str, object]] = [
        ("Title", market_label),
        ("Regime", _safe_text(payload.get("trend"), "neutral")),
        ("Edge", _safe_text(payload.get("edge_label"), _fmt_signed_percent(payload.get("edge")))),
        ("Summary", _compact_text(payload.get("insight"), "Monitoring market context", max_len=84)),
    ]
    if payload.get("market_id"):
        lines.append(("Ref", _safe_text(payload.get("market_id"))))
    return _section("📡 Market", _tree_group(lines))


def _render_operator_note(payload: Mapping[str, Any]) -> str:
    note = _compact_text(payload.get("operator_note"), "Monitoring with current safeguards.", max_len=100)
    return _section("💡 Operator Note", _tree_group([("Guidance", note)]))


def _render_empty_state(mode: str, payload: Mapping[str, Any]) -> str:
    if mode in {"positions", "trade"} and _safe_int(payload.get("positions")) <= 0:
        return _section(
            "🫥 Empty State",
            _tree_group(
                [
                    ("Status", "No positions found"),
                    ("Next", "Start trading to populate this view"),
                    ("Tip", "Use tabs to switch views quickly"),
                ]
            ),
        )
    if mode in {"market", "markets"} and not (
        payload.get("market_title") or payload.get("market_question") or payload.get("market_id")
    ):
        return _section(
            "🫥 Empty State",
            _tree_group(
                [
                    ("Status", "No market context available"),
                    ("Next", "Refresh markets to load context"),
                    ("Tip", "Title-first summary appears when metadata is available"),
                ]
            ),
        )
    return ""


def _render_meta(payload: Mapping[str, Any]) -> str:
    updated = _safe_text(payload.get("updated_at"), "")
    if not updated:
        updated = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:12]
    return f"🕒 Last updated: {updated}"


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

    blocks: list[str] = [_hero_block(mode, normalized), _primary_block(mode, normalized)]

    position_modes = {"positions", "trade", "exposure"}
    market_modes = {"market", "markets", "positions", "trade", "exposure"}

    if mode in position_modes:
        position_card = _render_position_card(normalized, market_label)
        if position_card:
            blocks.append(position_card)

    if mode in market_modes:
        blocks.append(_render_market_card(normalized, market_label))
    empty_state = _render_empty_state(mode, normalized)
    if empty_state:
        blocks.append(empty_state)
    blocks.append(_render_operator_note(normalized))
    blocks.append(_render_meta(normalized))

    return "\n\n".join(blocks)
