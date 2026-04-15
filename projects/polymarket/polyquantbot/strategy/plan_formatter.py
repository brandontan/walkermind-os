"""strategy.plan_formatter — Telegram-ready formatter for Fast Plan Bot output.

Converts a list of TradePlan objects into a premium Telegram UI string
using STYLE B SPACING SYSTEM V2 components consistent with the rest of
the PolyQuantBot UI surface.

Design:
    - Pure functions: no I/O, no side-effects.
    - Accepts Optional[list[TradePlan]] — handles empty and None gracefully.
    - Risk badge mapping: LOW → 🟢, MEDIUM → 🟡, HIGH → 🔴.
    - Truncates market title at 40 chars for mobile readability.
    - Outputs a self-contained Telegram Markdown string (no HTML).
"""
from __future__ import annotations

import datetime
from typing import List, Optional

from .plan_engine import TradePlan

# ── Constants ─────────────────────────────────────────────────────────────────

_SEP = "━━━━━━━━━━━━━━━━━━━━━━"
_SEP_THIN = "──────────────────────"
_LABEL_WIDTH = 12
_TITLE_MAX = 40

_RISK_BADGE: dict[str, str] = {
    "LOW": "🟢 LOW",
    "MEDIUM": "🟡 MEDIUM",
    "HIGH": "🔴 HIGH",
}

_DIR_BADGE: dict[str, str] = {
    "YES": "▲ YES",
    "NO": "▼ NO",
}


# ── Public API ─────────────────────────────────────────────────────────────────


def format_plan_list(
    plans: Optional[List[TradePlan]],
    mode: str = "PAPER",
    capital_usdc: float = 1_000.0,
) -> str:
    """Format a list of TradePlan objects as a Telegram Markdown message.

    Args:
        plans:          Plans produced by PlanEngine.generate_plans().
        mode:           Trading mode label ("PAPER" | "LIVE") for header.
        capital_usdc:   Capital used for context in the footer.

    Returns:
        Multi-line Markdown string ready for Telegram sendMessage.
    """
    status_label = f"[{mode}]"
    header_lines = [
        f"📋 *FAST PLAN BOT*  `{status_label}`",
        _SEP,
    ]

    if not plans:
        body_lines = [
            "⚠️ *NO PLANS GENERATED*",
            _SEP,
            _kv("STATUS", "No signals above threshold"),
            _kv("ACTION", "Markets need more data"),
            _SEP,
            "🧠 _Insight: Feed more market candidates or lower min\\_edge._",
        ]
        return "\n".join(header_lines + body_lines)

    body_lines: List[str] = []
    for idx, plan in enumerate(plans, start=1):
        body_lines.append(_format_single_plan(idx, plan))
        if idx < len(plans):
            body_lines.append("")  # blank line between cards

    footer_lines = [
        _SEP,
        _kv("CAPITAL", f"${capital_usdc:,.0f} USDC"),
        _kv("PLANS", str(len(plans))),
        _kv("KELLY α", "0.25 (fractional)"),
        _SEP,
        f"🧠 _Insight: Top plan by EV — {plans[0].reasoning}_",
        "",
        "_⚠ Plans are advisory only. No orders placed._",
    ]

    return "\n".join(header_lines + body_lines + footer_lines)


def format_plan_empty(mode: str = "PAPER") -> str:
    """Return a Telegram message for when no market candidates were supplied."""
    return "\n".join([
        f"📋 *FAST PLAN BOT*  `[{mode}]`",
        _SEP,
        "⚠️ *NO MARKETS*",
        _SEP,
        _kv("STATUS", "No candidates provided"),
        _kv("ACTION", "Supply market data first"),
        _SEP,
        "🧠 _Insight: Use /markets to discover active markets._",
    ])


# ── Internal helpers ───────────────────────────────────────────────────────────


def _format_single_plan(rank: int, plan: TradePlan) -> str:
    """Render a single TradePlan as a premium card block."""
    title = plan.market_title
    if len(title) > _TITLE_MAX:
        title = title[: _TITLE_MAX - 1] + "…"

    risk_badge = _RISK_BADGE.get(plan.risk_level, plan.risk_level)
    dir_badge = _DIR_BADGE.get(plan.direction, plan.direction)
    ev_sign = "+" if plan.expected_value >= 0 else ""
    sources_str = ", ".join(s.replace("_", " ").title() for s in plan.strategy_sources) or "N/A"
    ts_str = _format_ts(plan.generated_at)

    return "\n".join([
        f"*#{rank} — {title}*",
        _SEP_THIN,
        _kv("PLAN ID", f"`{plan.plan_id}`"),
        _kv("DIRECTION", dir_badge),
        _kv("ENTRY", f"{plan.entry_price:.4f}"),
        _kv("TARGET", f"{plan.target_price:.4f}"),
        _kv("SIZE", f"${plan.position_size_usdc:.2f}"),
        _kv("EDGE", f"{plan.edge_score:.1%}"),
        _kv("EV", f"{ev_sign}${plan.expected_value:.2f}"),
        _kv("Z-SCORE", f"{plan.z_score:.2f}"),
        _kv("CONFIDENCE", f"{plan.confidence:.1%}"),
        _kv("RISK", risk_badge),
        _kv("SIGNALS", sources_str),
        _kv("GENERATED", ts_str),
        _SEP_THIN,
    ])


def _kv(label: str, value: str) -> str:
    """Render a key-value line in STYLE B SPACING SYSTEM V2."""
    padded = f"{label.upper():<{_LABEL_WIDTH}}"
    return f"{padded} ● {value}"


def _format_ts(ts: float) -> str:
    """Format a UNIX timestamp as UTC string."""
    try:
        dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
        return dt.strftime("%H:%M UTC")
    except Exception:
        return "N/A"
