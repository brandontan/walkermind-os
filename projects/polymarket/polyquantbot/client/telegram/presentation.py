"""Telegram presentation helpers for public paper-beta live replies.

Pure formatting only: no I/O, no runtime side effects.
"""
from __future__ import annotations

from projects.polymarket.polyquantbot.telegram.ui.components import SEP, render_kv_line


def format_start_session_ready_reply() -> str:
    return (
        "🚀 CrusaderBot — Session Ready\n"
        f"{SEP}\n"
        "Your paper-beta session is active.\n\n"
        "Next steps:\n"
        "• /help — command guide\n"
        "• /status — runtime and guard snapshot\n\n"
        "Boundary:\n"
        "• Public-ready paper beta\n"
        "• Paper-only execution\n"
        "• Not live-trading ready\n"
        "• Not production-capital ready"
    )


def format_help_reply() -> str:
    lines = [
        "📘 CrusaderBot Help — Public Paper Beta",
        SEP,
        "Core commands",
        render_kv_line("/START", "Open or refresh your session"),
        render_kv_line("/HELP", "View this guide"),
        render_kv_line("/STATUS", "Runtime + guard snapshot"),
        SEP,
        "Paper control surfaces",
        render_kv_line("/MODE", "Set paper mode only"),
        render_kv_line("/AUTOTRADE", "Toggle paper autotrade"),
        render_kv_line("/POSITIONS", "Read open paper positions"),
        render_kv_line("/PNL", "Read paper PnL"),
        render_kv_line("/RISK", "Read risk state"),
        render_kv_line("/MARKETS", "Query market scan"),
        render_kv_line("/MARKET360", "View market detail"),
        render_kv_line("/SOCIAL", "View social pulse"),
        render_kv_line("/KILL", "Force paper kill switch"),
        SEP,
        "Boundary",
        "• Public-ready paper beta",
        "• Paper-only execution",
        "• Not live-trading ready",
        "• Not production-capital ready",
    ]
    return "\n".join(lines)


def format_status_reply(
    *,
    mode: str,
    managed_state: str,
    release_channel: str,
    entry_allowed: bool,
    guard_reasons: str,
    last_risk_reason: str,
    kill_switch: bool,
    autotrade: bool,
    position_count: int,
) -> str:
    return "\n".join(
        [
            "🧭 CrusaderBot Status — Public Paper Beta",
            SEP,
            "Runtime",
            render_kv_line("Mode", mode),
            render_kv_line("State", managed_state),
            render_kv_line("Channel", release_channel),
            SEP,
            "Safety",
            render_kv_line("Entry", str(entry_allowed)),
            render_kv_line("Reasons", guard_reasons),
            render_kv_line("Last risk", last_risk_reason),
            render_kv_line("Kill switch", str(kill_switch)),
            SEP,
            "Paper metrics",
            render_kv_line("Autotrade", str(autotrade)),
            render_kv_line("Positions", str(position_count)),
            SEP,
            "Boundary: paper-only execution. Not live-trading ready. Not production-capital ready.",
        ]
    )

