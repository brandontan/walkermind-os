"""Telegram presentation helpers for public paper-beta live replies.

Pure formatting only: no I/O, no runtime side effects.
"""
from __future__ import annotations

from projects.polymarket.polyquantbot.telegram.ui.components import SEP, render_kv_line


_PUBLIC_BOUNDARY_LINES = (
    "• Public-ready paper beta",
    "• Paper-only execution",
    "• Not live-trading ready",
    "• Not production-capital ready",
)


def _format_public_screen(title: str, body_lines: list[str], *, next_steps: list[str] | None = None) -> str:
    lines: list[str] = [title, SEP] + body_lines
    if next_steps:
        lines.extend(["", "Next steps:"] + [f"• {step}" for step in next_steps])
    lines.extend(["", "Boundary:"] + list(_PUBLIC_BOUNDARY_LINES))
    return "\n".join(lines)


def format_start_session_ready_reply() -> str:
    return _format_public_screen(
        "🚀 CrusaderBot — Session Ready",
        ["Your paper-beta session is active and safe to explore."],
        next_steps=[
            "/help — open the public command guide",
            "/status — check runtime and guard state",
        ],
    )


def format_start_first_required_reply() -> str:
    return _format_public_screen(
        "⚠️ Onboarding required",
        [
            "This command is available after onboarding starts.",
            "Use /start to open onboarding, then retry your command.",
        ],
    )


def format_onboarding_started_reply() -> str:
    return _format_public_screen(
        "✅ Onboarding started",
        [
            "Your onboarding path is now created.",
            "Send /start again to continue into session activation.",
        ],
    )


def format_already_linked_reply() -> str:
    return _format_public_screen(
        "ℹ️ Account already linked",
        [
            "This Telegram account is already linked.",
            "Send /start to continue into session activation.",
        ],
    )


def format_activation_ready_reply() -> str:
    return _format_public_screen(
        "✅ Account activated",
        [
            "Activation is complete.",
            "Send /start again to open your session.",
        ],
    )


def format_already_active_session_reply() -> str:
    return _format_public_screen(
        "✅ Session already active",
        ["Welcome back — your paper-beta session is ready."],
        next_steps=["/help", "/status"],
    )


def format_temporary_identity_error_reply() -> str:
    return _format_public_screen(
        "⚠️ Temporary identity check issue",
        [
            "We couldn't verify your identity right now.",
            "Please try /start again shortly.",
        ],
    )


def format_onboarding_rejected_reply() -> str:
    return _format_public_screen(
        "⚠️ Onboarding unavailable",
        [
            "We couldn't start onboarding right now.",
            "Please try again later or contact support.",
        ],
    )


def format_activation_rejected_reply() -> str:
    return _format_public_screen(
        "⚠️ Activation unavailable",
        [
            "Activation is not available for this account right now.",
            "Please contact support if this seems unexpected.",
        ],
    )


def format_runtime_temporary_error_reply() -> str:
    return _format_public_screen(
        "⚠️ Temporary runtime issue",
        [
            "The bot runtime is temporarily unavailable.",
            "Please retry your command in a moment.",
        ],
    )


def format_start_rejected_reply(detail: str) -> str:
    reason = detail or "not available"
    return _format_public_screen(
        "⚠️ Session could not be opened",
        [f"Reason: {reason}", "Please send /start again shortly."],
    )


def format_start_temp_backend_error_reply() -> str:
    return _format_public_screen(
        "⚠️ Temporary backend issue",
        [
            "We hit a backend issue while opening your session.",
            "Please send /start again shortly.",
        ],
    )


def format_unknown_command_reply() -> str:
    return _format_public_screen(
        "⚠️ Command not recognized",
        [
            "Try one of these public commands:",
            "• /start",
            "• /help",
            "• /status",
            "",
            "Advanced controls are operator-managed during paper beta",
            "and intentionally hidden from the public command guide.",
        ],
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
        "Public posture",
        "• Public-safe command set is intentionally small during paper beta.",
        "• Advanced controls remain operator-managed until broader readiness proof.",
        SEP,
        "Boundary",
        "• Public-ready paper beta",
        "• Paper-only execution",
        "• Not live-trading ready",
        "• Not production-capital ready",
    ]
    return "\n".join(lines)


def format_pnl_reply(
    *,
    realized: float,
    unrealized: float,
    cash: float,
    equity: float,
    position_count: int,
) -> str:
    net = realized + unrealized
    r_sign = "+" if realized >= 0 else ""
    u_sign = "+" if unrealized >= 0 else ""
    n_sign = "+" if net >= 0 else ""
    return _format_public_screen(
        "💰 CrusaderBot PnL — Paper Account",
        [
            render_kv_line("Realized", f"{r_sign}${realized:,.4f}"),
            render_kv_line("Unrealized", f"{u_sign}${unrealized:,.4f}"),
            render_kv_line("Net PnL", f"{n_sign}${net:,.4f}"),
            SEP,
            render_kv_line("Cash", f"${cash:,.2f}"),
            render_kv_line("Equity", f"${equity:,.2f}"),
            render_kv_line("Open positions", str(position_count)),
        ],
    )


def format_portfolio_reset_reply(*, initial_balance: float) -> str:
    return _format_public_screen(
        "🔄 Paper Account Reset",
        [
            "Paper account has been reset to initial balance.",
            render_kv_line("Balance", f"${initial_balance:,.2f}"),
            "All positions, ledger, and PnL history cleared.",
        ],
        next_steps=["/status — confirm runtime state", "/pnl — verify balance"],
    )


def format_risk_state_reply(status: dict) -> str:
    ks = "🔴 ACTIVE" if status.get("kill_switch") else "🟢 OFF"
    dd_ok = "✅" if status.get("drawdown_ok") else "🚨"
    exp_ok = "✅" if status.get("exposure_ok") else "🚨"
    pnl_ok = "✅" if status.get("daily_pnl_ok") else "🚨"
    return _format_public_screen(
        "🛡 Paper Risk Gate — Live State",
        [
            render_kv_line("Kill switch", ks),
            render_kv_line("Mode", str(status.get("mode", "paper"))),
            SEP,
            render_kv_line("Drawdown", f"{dd_ok} {status.get('drawdown_pct', 0):.2f}% / {status.get('drawdown_limit_pct', 8)}% limit"),
            render_kv_line("Exposure", f"{exp_ok} {status.get('exposure_pct', 0):.2f}% / {status.get('exposure_limit_pct', 10)}% limit"),
            render_kv_line("Daily PnL", f"{pnl_ok} ${status.get('daily_pnl_usd', 0):,.2f} (limit $-2,000)"),
            SEP,
            render_kv_line("Cash", f"${status.get('wallet_cash', 0):,.2f}"),
            render_kv_line("Equity", f"${status.get('wallet_equity', 0):,.2f}"),
            render_kv_line("Positions", str(status.get("open_positions", 0))),
            render_kv_line("Last reason", str(status.get("last_risk_reason", "—"))),
        ],
    )


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
    return _format_public_screen(
        "🧭 CrusaderBot Status — Public Paper Beta",
        [
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
        ],
    )
