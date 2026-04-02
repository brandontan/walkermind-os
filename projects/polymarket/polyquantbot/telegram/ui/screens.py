"""Screen text templates — pure formatting, no business logic.

Each function returns a Markdown-formatted string ready for Telegram.
No side effects, no I/O.  All strings use Telegram Markdown conventions
(``*bold*``, ``_italic_``, `` `code` ``).
"""
from __future__ import annotations


# ── Main screen ────────────────────────────────────────────────────────────────


def main_screen(mode: str, state: str) -> str:
    """Top-level navigation screen."""
    return (
        f"*KrusaderBot* — Polymarket AI Trader\n"
        f"Mode: `{mode}` | State: `{state}`"
    )


# ── Status screens ─────────────────────────────────────────────────────────────


def status_screen(
    state: str,
    reason: str,
    mode: str,
    risk_multiplier: float,
    max_position: float,
    pipeline_lines: list[str] | None = None,
) -> str:
    """Full system status overview."""
    lines = [
        "📊 *SYSTEM STATUS*",
        "",
        f"State: `{state}`",
        f"Reason: `{reason or '-'}`",
        f"Mode: `{mode}`",
        f"Risk: `{risk_multiplier:.3f}` | MaxPos: `{max_position:.3f}`",
    ]
    if pipeline_lines:
        lines += ["", "*Pipeline*"] + pipeline_lines
    return "\n".join(lines)


def performance_screen(total_pnl: float, total_trades: int, mode: str) -> str:
    """PnL + trades performance summary."""
    return (
        "📈 *PERFORMANCE*\n\n"
        f"Mode: `{mode}`\n"
        f"Total PnL: `{total_pnl:.4f} USD`\n"
        f"Total Trades: `{total_trades}`"
    )


def strategies_screen(snapshot: dict, conflicts: int = 0) -> str:
    """Per-strategy metrics snapshot."""
    if not snapshot:
        return "📋 *STRATEGIES*\n\nNo strategy data available."
    lines = ["📋 *STRATEGIES*\n"]
    for strategy_id, data in snapshot.items():
        trades = data.get("trades_executed", 0)
        signals = data.get("signals_generated", 0)
        pnl = data.get("total_pnl", 0.0)
        lines.append(
            f"*{strategy_id}*\n"
            f"  Signals: `{signals}` | Trades: `{trades}` | PnL: `{pnl:.4f}`"
        )
    if conflicts:
        lines.append(f"\n⚡ Conflicts: `{conflicts}`")
    return "\n".join(lines)


# ── Wallet screens ─────────────────────────────────────────────────────────────


def wallet_screen(mode: str) -> str:
    """Wallet / portfolio overview."""
    return (
        "💰 *WALLET*\n\n"
        f"Mode: `{mode}`\n"
        "Live exposure data available via /health.\n"
        "_Direct wallet integration active in next phase._"
    )


def wallet_balance_screen(balance: float | None = None) -> str:
    """Balance detail screen."""
    if balance is not None:
        return f"💵 *Balance*\n`{balance:.4f} USD`"
    return "💵 *Balance*\n_Not yet available — use /health for exposure data._"


def wallet_exposure_screen(exposure: float | None = None) -> str:
    """Open exposure detail screen."""
    if exposure is not None:
        return f"📉 *Open Exposure*\n`{exposure:.4f} USD`"
    return "📉 *Open Exposure*\n_Not yet available — use /health for exposure data._"


# ── Settings screens ───────────────────────────────────────────────────────────


def settings_screen(mode: str, risk_multiplier: float, max_position: float) -> str:
    """Settings overview."""
    return (
        "⚙️ *SETTINGS*\n\n"
        f"Trading Mode: `{mode}`\n"
        f"Risk Multiplier: `{risk_multiplier:.3f}`\n"
        f"Max Position: `{max_position:.3f}` ({max_position * 100:.1f}%)\n\n"
        "_Select a setting to modify:_"
    )


def settings_risk_screen() -> str:
    """Risk level prompt."""
    return "⚠️ *Risk Level*\nSend `/set_risk [0.1–1.0]` to update the risk multiplier."


def settings_mode_screen(current_mode: str, new_mode: str) -> str:
    """Mode switch confirmation prompt."""
    return (
        f"🔀 *Mode Switch*\n"
        f"Switch from `{current_mode}` → `{new_mode}`?\n\n"
        f"⚠️ Confirm before proceeding."
    )


def settings_notify_screen() -> str:
    """Notification settings info."""
    return "🔔 *Notifications*\nAlerts enabled for: trade executed, warning, critical error."


def settings_auto_screen(mode: str) -> str:
    """Auto trade info."""
    return (
        f"🤖 *Auto Trade*\n"
        f"Mode: `{mode}`\n"
        "System trades automatically when state is RUNNING."
    )


def mode_switched_screen(new_mode: str) -> str:
    """Mode switch confirmation."""
    return f"✅ Mode switched to `{new_mode}`."


# ── Control screens ────────────────────────────────────────────────────────────


def control_screen(state_str: str) -> str:
    """Control panel overview."""
    return f"▶ *CONTROL*\nSystem state: `{state_str}`"


def control_stop_confirm_screen() -> str:
    """Stop/halt confirmation prompt."""
    return "🛑 *Stop Trading*\nThis will HALT the system. Are you sure?"


def control_paused_screen() -> str:
    return "⏸ Trading *PAUSED*."


def control_resumed_screen() -> str:
    return "▶️ Trading *RESUMED*."


def control_halted_screen() -> str:
    return "🛑 Trading *HALTED*. Manual restart required."


# ── Generic ────────────────────────────────────────────────────────────────────


def error_screen(context: str, error: str) -> str:
    """Generic error display."""
    return f"⚠️ *Error in {context}*\n`{error}`"


def noop_screen() -> str:
    """Empty screen — no message update needed."""
    return ""
