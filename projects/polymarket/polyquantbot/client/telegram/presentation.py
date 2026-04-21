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


def format_start_first_required_reply() -> str:
    return (
        "⚠️ Onboarding required before this command\n"
        f"{SEP}\n"
        "Use /start first to begin onboarding.\n"
        "After onboarding is ready, retry your command.\n\n"
        "Boundary:\n"
        "• Public-ready paper beta\n"
        "• Paper-only execution\n"
        "• Not live-trading ready\n"
        "• Not production-capital ready"
    )


def format_onboarding_started_reply() -> str:
    return (
        "✅ Onboarding started\n"
        f"{SEP}\n"
        "We created your onboarding path.\n"
        "Send /start again to continue into session activation.\n\n"
        "Boundary: paper-only public beta."
    )


def format_already_linked_reply() -> str:
    return (
        "ℹ️ Account already linked\n"
        f"{SEP}\n"
        "Your Telegram account is already linked.\n"
        "Send /start to continue into session activation."
    )


def format_activation_ready_reply() -> str:
    return (
        "✅ Account activated\n"
        f"{SEP}\n"
        "Activation is complete.\n"
        "Send /start again to open your session."
    )


def format_already_active_session_reply() -> str:
    return (
        "✅ Session already active\n"
        f"{SEP}\n"
        "Welcome back — your paper-beta session is ready.\n"
        "Use /help or /status for next actions."
    )


def format_temporary_identity_error_reply() -> str:
    return (
        "⚠️ Temporary identity check issue\n"
        f"{SEP}\n"
        "We couldn't verify your identity right now.\n"
        "Please try again shortly."
    )


def format_onboarding_rejected_reply() -> str:
    return (
        "⚠️ Onboarding unavailable right now\n"
        f"{SEP}\n"
        "We couldn't start onboarding at the moment.\n"
        "Please try again later or contact support."
    )


def format_activation_rejected_reply() -> str:
    return (
        "⚠️ Activation unavailable for this account\n"
        f"{SEP}\n"
        "Activation is not available right now.\n"
        "Please contact support if this seems unexpected."
    )


def format_runtime_temporary_error_reply() -> str:
    return (
        "⚠️ Temporary runtime issue\n"
        f"{SEP}\n"
        "Please retry your command in a moment."
    )


def format_start_rejected_reply(detail: str) -> str:
    reason = detail or "not available"
    return (
        "⚠️ Session could not be opened right now\n"
        f"{SEP}\n"
        f"Reason: {reason}\n"
        "Please send /start again shortly."
    )


def format_start_temp_backend_error_reply() -> str:
    return (
        "⚠️ Temporary backend issue\n"
        f"{SEP}\n"
        "We hit a backend issue while opening your session.\n"
        "Please send /start again shortly."
    )


def format_unknown_command_reply() -> str:
    return (
        "⚠️ Command not recognized\n"
        f"{SEP}\n"
        "Try one of these:\n"
        "• /start\n"
        "• /help\n"
        "• /status\n"
        "• /mode /autotrade /positions /pnl /risk /markets /market360 /social /kill\n\n"
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
