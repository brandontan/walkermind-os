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


def performance_screen(
    total_pnl: float,
    total_trades: int,
    mode: str,
    win_rate: float = 0.0,
    drawdown: float = 0.0,
) -> str:
    """PnL + trades performance summary."""
    pnl_sign = "+" if total_pnl >= 0 else ""
    return (
        "📈 *PERFORMANCE*\n\n"
        f"Mode: `{mode}`\n"
        f"Total PnL: `{pnl_sign}{total_pnl:.4f} USD`\n"
        f"Win Rate: `{win_rate:.1%}`\n"
        f"Trades: `{total_trades}`\n"
        f"Drawdown: `{drawdown:.2%}`"
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


def wallet_screen(
    mode: str,
    address: str | None = None,
    balance: float | None = None,
) -> str:
    """Wallet / portfolio overview showing address and live balance."""
    addr_line = f"`{address}`" if address else "_No wallet yet — tap Refresh to create._"
    bal_line = f"`{balance:.4f} USDC`" if balance is not None else "_Tap Balance to fetch._"
    return (
        "💰 *WALLET*\n\n"
        f"Mode: `{mode}`\n"
        f"Address: {addr_line}\n"
        f"Balance: {bal_line}"
    )


def wallet_balance_screen(balance: float | None = None, address: str | None = None) -> str:
    """Balance detail screen showing available, locked and total breakdown."""
    lines = ["💰 *BALANCE*\n"]
    if address:
        lines.append(f"Address: `{address}`\n")
    if balance is not None:
        # WalletService returns portfolio value; locked positions are tracked separately
        available = balance
        locked = 0.0
        total = balance
        lines.append(f"Available: `${available:.4f}`")
        lines.append(f"Locked: `${locked:.4f}`")
        lines.append(f"Total: `${total:.4f}`")
    else:
        lines.append("_Balance fetch in progress…_")
    return "\n".join(lines)


def wallet_exposure_screen(exposure: float | None = None) -> str:
    """Open exposure detail screen."""
    if exposure is not None:
        return f"📉 *Open Exposure*\n`{exposure:.4f} USD`"
    return "📉 *Open Exposure*\n_Not yet available — use /health for exposure data._"


def wallet_withdraw_screen(
    address: str | None = None,
    balance: float | None = None,
) -> str:
    """Withdraw initiation screen."""
    addr_line = f"`{address}`" if address else "_No wallet._"
    bal_line = f"`{balance:.4f} USDC`" if balance is not None else "_unknown_"
    return (
        "💸 *WITHDRAW*\n\n"
        f"From: {addr_line}\n"
        f"Available: {bal_line}\n\n"
        "_To initiate a withdrawal, reply with:_\n"
        "`/withdraw <to_address> <amount>`"
    )


def wallet_withdraw_result_screen(result: dict) -> str:
    """Withdraw result screen after broadcast attempt."""
    status = result.get("status", "unknown")
    to_addr = result.get("to_address", "?")
    amount = result.get("amount_usdc", 0.0)
    tx_hash = result.get("tx_hash")
    note = result.get("note", "")

    if status == "broadcast":
        return (
            "✅ *WITHDRAW SUBMITTED*\n\n"
            f"To: `{to_addr}`\n"
            f"Amount: `{amount:.4f} USDC`\n"
            f"Tx: `{tx_hash}`"
        )
    lines = [
        "⏳ *WITHDRAW QUEUED*\n",
        f"To: `{to_addr}`",
        f"Amount: `{amount:.4f} USDC`",
        f"Status: `{status}`",
    ]
    if note:
        lines.append(f"_{note}_")
    return "\n".join(lines)


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


def settings_risk_screen(current_value: float = 0.25) -> str:
    """Risk level prompt with current value, descriptions, and hybrid UI options."""
    return (
        f"⚠️ *Risk Level*\n\n"
        f"Current: `{current_value:.2f}`\n\n"
        "0.10 → Very conservative (small size)\n"
        "0.25 → Conservative\n"
        "0.50 → Balanced\n"
        "1.00 → Aggressive\n\n"
        "_Uses fractional Kelly (0.25f)_\n\n"
        "Select a preset or use `/set_risk [value]` for custom:"
    )


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
    """Structured error screen with diagnostics and actionable insight."""
    from .components import render_insight, SEP  # noqa: PLC0415
    return "\n".join([
        "⚠️ *SYSTEM NOTICE*",
        SEP,
        f"*Context:* `{context}`",
        "",
        "📋 *Diagnostics:*",
        f"_{error}_",
        "",
        "⚡ *What to do:*",
        "_Check connection, retry, or contact support if persistent._",
        SEP,
        render_insight("System encountered an issue — monitoring recovery"),
    ])


def noop_screen() -> str:
    """Empty screen — no message update needed."""
    return ""


def positions_screen(positions: list[dict]) -> str:
    """Open positions detail screen.

    Args:
        positions: List of position dicts with keys:
            ``question``, ``side``, ``avg_price``, ``size``, ``unrealized_pnl``.

    Returns:
        Markdown-formatted positions summary.
    """
    if not positions:
        return "📋 *POSITIONS*\n\n_No open positions._"

    lines = [f"📋 *POSITIONS* ({len(positions)} open)\n"]
    for pos in positions:
        question = pos.get("question") or pos.get("market_id", "Unknown")
        side = pos.get("side", "?")
        avg_price = float(pos.get("avg_price", 0.0))
        size = float(pos.get("size", 0.0))
        upnl = float(pos.get("unrealized_pnl", 0.0))
        upnl_sign = "+" if upnl >= 0 else ""
        # Truncate long questions for readability
        if len(question) > 48:
            question = question[:45] + "…"
        lines.append(
            f"*{question}*\n"
            f"  Side: `{side}` | Avg: `{avg_price:.4f}` | Size: `{size:.4f}`\n"
            f"  Unrealized PnL: `{upnl_sign}{upnl:.4f} USD`"
        )
    return "\n\n".join(lines)


def pnl_screen(realized: float, unrealized: float, total: float) -> str:
    """PnL summary screen.

    Args:
        realized:   Total realized PnL in USD.
        unrealized: Total unrealized PnL in USD.
        total:      Combined total PnL in USD.

    Returns:
        Markdown-formatted PnL summary.
    """
    def _sign(v: float) -> str:
        return "+" if v >= 0 else ""

    return (
        "💹 *PnL SUMMARY*\n\n"
        f"Realized:   `{_sign(realized)}{realized:.4f} USD`\n"
        f"Unrealized: `{_sign(unrealized)}{unrealized:.4f} USD`\n"
        f"Total:      `{_sign(total)}{total:.4f} USD`"
    )
