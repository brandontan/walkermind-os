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
    "active_scope": "✅ Active Scope",
    "help": "❓ Help",
    "guidance": "🧭 Guidance",
    "bot_info": "ℹ️ Bot Info",
}

ROOT_LABELS: dict[str, str] = {
    "dashboard": "📊 Dashboard",
    "portfolio": "💼 Portfolio",
    "markets": "🎯 Markets",
    "settings": "⚙️ Settings",
    "help": "❓ Help",
}
TRADE_HISTORY_LIMIT = 10


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


def _safe_text(value: object, default: str = "Unavailable") -> str:
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    if text.lower() in {"n/a", "na", "none", "null", "nan", "-"}:
        return default
    return text


def _compact_text(value: object, default: str = "Unavailable", max_len: int = 72) -> str:
    text = _safe_text(value, default)
    return text if len(text) <= max_len else f"{text[: max_len - 1]}…"


def _as_text_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [_safe_text(item, "").strip() for item in value if _safe_text(item, "").strip()]
    return []


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


def _side_text(value: object) -> str:
    side = _safe_text(value, "UNKNOWN").upper()
    if side in {"BUY", "LONG", "YES"}:
        return "YES"
    if side in {"SELL", "SHORT", "NO"}:
        return "NO"
    return side


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


def _contains_ref_fragment(label: str, market_id: str) -> bool:
    lowered = label.lower()
    candidate = market_id.lower()
    short = candidate[:12]
    return "ref" in lowered and short and short in lowered


def _resolve_market_label(payload: Mapping[str, Any], context: Mapping[str, Any]) -> str:
    def _is_generic_label(text: str) -> bool:
        compact = text.strip().lower()
        return compact in {"market", "market #", "untitled", "untitled market", "unknown", "unknown market"} or compact.startswith("market #")

    def _is_internal_fallback_label(text: str) -> bool:
        lowered = text.lower()
        return "(ref" in lowered or lowered.startswith("ref ") or "market_id" in lowered

    for candidate in (
        payload.get("market_title"),
        context.get("question"),
    ):
        text = _compact_text(candidate, "", max_len=86)
        if text and not _is_generic_label(text) and not _is_internal_fallback_label(text):
            return text
    fallback_market_id = _safe_text(payload.get("market_id"), "")
    if fallback_market_id:
        return f"Market {fallback_market_id[:12]}"
    return "Untitled Market"


def _hero_block(mode: str, payload: Mapping[str, Any]) -> str:
    status = _safe_text(payload.get("state"), "waiting").upper()
    decision = _compact_text(payload.get("decision"), "Await qualified signal", max_len=84)
    risk_state = _compact_text(payload.get("risk_state"), "within limits", max_len=56)
    active_root = _safe_text(payload.get("active_root"), "dashboard").lower()
    active_label = ROOT_LABELS.get(active_root, ROOT_LABELS["dashboard"])
    return _section(
        VIEW_TITLE.get(mode, VIEW_TITLE["home"]),
        _tree_group(
            [
                ("Section", f"● {active_label}"),
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
                ("Scope", _safe_text(payload.get("scope_label"), "All Markets")),
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
            "💰 Account Capital",
            [
                ("Total Value", _fmt_currency(payload.get("equity"))),
                ("Available Balance", _fmt_currency(payload.get("available_balance", payload.get("equity")))),
                ("Realized PnL", _fmt_signed_currency(payload.get("realized_pnl"))),
            ],
        ),
        "positions": (
            "📌 Position State",
            [
                ("Open Positions", _safe_int(payload.get("positions"))),
                ("Unrealized", _fmt_signed_currency(payload.get("unrealized_pnl", payload.get("pnl")))),
                ("Largest Position", _fmt_currency(payload.get("largest_position_size"))),
            ],
        ),
        "trade": (
            "🧭 Trade Focus",
            [
                ("Side", _direction(payload.get("side"))),
                ("Signal Confidence", _fmt_percent(payload.get("confidence"), already_percent=True)),
                ("Edge", _safe_text(payload.get("edge_label"), _fmt_signed_percent(payload.get("edge")))),
            ],
        ),
        "pnl": (
            "💰 PnL State",
            [
                ("Unrealized", _fmt_signed_currency(payload.get("unrealized_pnl", payload.get("pnl")))),
                ("Realized", _fmt_signed_currency(payload.get("realized_pnl"))),
                ("Active Positions", _safe_int(payload.get("positions"))),
            ],
        ),
        "performance": (
            "🏁 Performance Scorecard",
            [
                ("Net PnL", _fmt_signed_currency(payload.get("pnl"))),
                ("Win Rate", _fmt_percent(payload.get("winrate"))),
                ("Trades", _safe_int(payload.get("trades"))),
            ],
        ),
        "exposure": (
            "🧱 Exposure Posture",
            [
                ("Portfolio Exposure", _fmt_percent(payload.get("exposure"))),
                ("Exposed Markets", _safe_int(payload.get("positions"))),
                ("Concentration", _fmt_percent(payload.get("concentration_ratio", payload.get("exposure")))),
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
                ("Selection", _safe_text(payload.get("selection_type"), "All Markets")),
                ("Categories", _safe_int(payload.get("active_categories_count"))),
                ("Focus", _compact_text(payload.get("trading_scope_summary"), "Scan for asymmetric opportunity", max_len=56)),
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
                ("Target", _safe_text(payload.get("target_mode"), "Unavailable")),
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
        "active_scope": (
            "✅ Trading Scope",
            [
                ("Selection Type", _safe_text(payload.get("selection_type"), "All Markets")),
                ("Active Categories", _safe_int(payload.get("active_categories_count"))),
                ("Enabled", _compact_text(", ".join(_as_text_list(payload.get("enabled_categories"))) or "No categories selected", max_len=86)),
                ("Summary", _compact_text(payload.get("trading_scope_summary"), "Trading scope: all allowed markets.", max_len=86)),
                ("Fallback Rule", _compact_text(payload.get("scope_fallback_policy"), "Disabled", max_len=86)),
                ("Persistence", "Scope restored after restart/re-init"),
            ],
        ),
        "help": (
            "❓ Help Center",
            [
                ("Guidance", "How to use menus and scope controls"),
                ("Bot Info", "Runtime behavior and control surfaces"),
                ("Style", "Concise and mobile-first"),
            ],
        ),
        "guidance": (
            "🧭 Operator Guidance",
            [
                ("Main Menu", "Dashboard · Portfolio · Markets · Settings · Help"),
                ("Scope Control", "Markets → All Markets / Categories / Active Scope"),
                ("Refresh", "Use Refresh All in Dashboard or Markets"),
            ],
        ),
        "bot_info": (
            "ℹ️ Bot Runtime",
            [
                ("Pipeline", "DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION → MONITORING"),
                ("Risk", "Risk checks remain enforced before execution"),
                ("Scope", _compact_text(payload.get("trading_scope_summary"), "Trading scope: all allowed markets.", max_len=86)),
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
        f"|- Market: {market_label}",
        f"|- Side: {_side_text(payload.get('side'))}",
        f"|- Entry: {_fmt_probability_cents(payload.get('entry'))}",
        f"|- Now: {_fmt_probability_cents(now_value)}",
        f"|- Size: {_fmt_currency(payload.get('size'))}",
        f"|- UPNL: {_fmt_signed_currency(payload.get('unrealized_pnl', payload.get('pnl')))}",
        f"|- Opened: {_format_opened_time(payload.get('opened_at'))}",
        f"|- Status: {_safe_text(payload.get('position_status'), 'Monitoring')}",
    ]
    market_id = _safe_text(payload.get("market_id"), "")
    if market_id and not _contains_ref_fragment(market_label, market_id):
        lines.append(f"|- Ref: {_safe_text(payload.get('position_id'), market_id)[:18]}")
    return "\n".join(["🎯 Position", *lines])


def _normalize_position_rows(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = payload.get("position_rows")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, Mapping)]


async def _render_position_cards(payload: Mapping[str, Any]) -> list[str]:
    rows = _normalize_position_rows(payload)
    if not rows:
        market_context = await get_market_context(_safe_text(payload.get("market_id"), "")) or {}
        market_label = _resolve_market_label(payload, market_context)
        single_card = _render_position_card(payload, market_label)
        return [single_card] if single_card else []

    cards: list[str] = []
    for row in rows:
        row_payload: dict[str, Any] = dict(payload)
        row_payload.update(
            {
                "market_id": row.get("market_id"),
                "market_title": row.get("market_title"),
                "side": row.get("side"),
                "entry": row.get("entry_price", row.get("avg_price")),
                "current": row.get("current_price", row.get("entry_price", row.get("avg_price"))),
                "size": row.get("size"),
                "unrealized_pnl": row.get("unrealized_pnl", row.get("pnl", 0.0)),
                "opened_at": row.get("opened_at"),
                "position_status": row.get("position_status", payload.get("position_status")),
                "position_id": row.get("position_id", row.get("market_id")),
            }
        )
        row_context = await get_market_context(_safe_text(row_payload.get("market_id"), "")) or {}
        row_label = _resolve_market_label(row_payload, row_context)
        card = _render_position_card(row_payload, row_label)
        if card:
            cards.append(card)
    return cards


def _normalize_trade_history_rows(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = payload.get("trade_history_rows")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, Mapping)]


def _render_closed_trade_card(row: Mapping[str, Any]) -> str:
    pnl = _safe_float(row.get("pnl"), 0.0)
    result = _safe_text(row.get("result"), "WIN" if pnl >= 0 else "LOSS").upper()
    return "\n".join(
        [
            "🏁 Closed Trade",
            f"|- Market: {_compact_text(row.get('market_title'), _safe_text(row.get('market_id'), 'Untitled Market'), max_len=86)}",
            f"|- Side: {_side_text(row.get('side'))}",
            f"|- Entry: {_fmt_probability_cents(row.get('entry_price'))}",
            f"|- Exit: {_fmt_probability_cents(row.get('exit_price'))}",
            f"|- PnL: {_fmt_signed_currency(pnl)}",
            f"|- Result: {result}",
            f"|- Closed: {_format_opened_time(row.get('closed_at'))}",
        ]
    )


def _render_trade_history(payload: Mapping[str, Any]) -> str:
    rows = _normalize_trade_history_rows(payload)
    if not rows:
        return "\n".join(["📜 Trade History", "No trade history yet"])

    cards = [_render_closed_trade_card(row) for row in rows[:TRADE_HISTORY_LIMIT]]
    return "\n\n".join(["📜 Trade History", *cards])


def _render_market_card(payload: Mapping[str, Any], market_label: str) -> str:
    lines: list[tuple[str, object]] = [
        ("Title", market_label),
        ("Regime", _safe_text(payload.get("trend"), "neutral")),
        ("Edge", _safe_text(payload.get("edge_label"), _fmt_signed_percent(payload.get("edge")))),
        ("Summary", _compact_text(payload.get("insight"), "Monitoring market context", max_len=84)),
    ]
    market_id = _safe_text(payload.get("market_id"), "")
    if market_id and not _contains_ref_fragment(market_label, market_id):
        lines.append(("Ref", market_id))
    return _section("📡 Market", _tree_group(lines))


def _render_exposure_card(payload: Mapping[str, Any]) -> str:
    return _section(
        "📊 Exposure Summary",
        _tree_group(
            [
                ("Total Exposure", _fmt_percent(payload.get("exposure"))),
                ("Exposed Markets", _safe_int(payload.get("positions"))),
                ("Largest Position", _fmt_currency(payload.get("largest_position_size"))),
            ]
        ),
    )


def _render_pnl_card(payload: Mapping[str, Any]) -> str:
    return _section(
        "📉 PnL Movement",
        _tree_group(
            [
                ("Current Unrealized", _fmt_signed_currency(payload.get("unrealized_pnl", payload.get("pnl")))),
                ("Current Realized", _fmt_signed_currency(payload.get("realized_pnl"))),
                ("Active Position", "Yes" if _safe_int(payload.get("positions")) > 0 else "No"),
            ]
        ),
    )


def _render_performance_card(payload: Mapping[str, Any]) -> str:
    return _section(
        "📈 Session Performance",
        _tree_group(
            [
                ("Trades", _safe_int(payload.get("trades"))),
                ("Win Rate", _fmt_percent(payload.get("winrate"))),
                ("Max Drawdown", _fmt_percent(payload.get("drawdown"))),
            ]
        ),
    )


def _render_operator_note(payload: Mapping[str, Any]) -> str:
    note = _compact_text(payload.get("operator_note"), "Monitoring with current safeguards.", max_len=100)
    return _section("💡 Operator Note", _tree_group([("Guidance", note)]))


def _render_scope_warning(payload: Mapping[str, Any]) -> str:
    warning = _safe_text(payload.get("scope_warning"), "")
    if not warning:
        return ""
    return _section("⚠️ Scope Warning", _tree_group([("Action Required", warning)]))


def _render_empty_state(mode: str, payload: Mapping[str, Any]) -> str:
    if mode == "positions" and _safe_int(payload.get("positions")) <= 0:
        return "No open positions"
    if mode == "exposure" and _safe_int(payload.get("positions")) <= 0:
        return _section(
            "🫥 Empty State",
            _tree_group(
                [
                    ("Status", "No market exposure"),
                    ("Next", "Exposure will appear once positions are opened"),
                    ("Tip", "Wallet and risk limits are still monitored"),
                ]
            ),
        )
    if mode == "pnl" and _safe_int(payload.get("positions")) <= 0:
        return _section(
            "🫥 Empty State",
            _tree_group(
                [
                    ("Status", "No active PnL movement"),
                    ("Next", "Realized and unrealized values update after trades"),
                    ("Tip", "Use Performance view for session scorecard"),
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
        "unrealized_pnl": pnl,
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

    if mode == "positions":
        position_cards = await _render_position_cards(normalized)
        if position_cards:
            blocks.extend(position_cards)
        else:
            blocks.append("No open positions")
        blocks.append(_render_trade_history(normalized))
    elif mode == "trade":
        position_card = _render_position_card(normalized, market_label)
        if position_card:
            blocks.append(position_card)

    if mode in {"market", "markets", "positions", "trade"}:
        blocks.append(_render_market_card(normalized, market_label))

    if mode == "exposure":
        blocks.append(_render_exposure_card(normalized))
    elif mode == "pnl":
        blocks.append(_render_pnl_card(normalized))
    elif mode == "performance":
        blocks.append(_render_performance_card(normalized))

    empty_state = _render_empty_state(mode, normalized)
    if empty_state:
        blocks.append(empty_state)
    scope_warning = _render_scope_warning(normalized)
    if scope_warning:
        blocks.append(scope_warning)
    blocks.append(_render_operator_note(normalized))
    blocks.append(_render_meta(normalized))

    return "\n\n".join(blocks)
