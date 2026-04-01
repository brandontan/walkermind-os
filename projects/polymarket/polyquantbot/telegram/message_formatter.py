"""Phase 10.7 — TelegramMessageFormatter: Centralized Telegram message formatting.

ALL Telegram messages in the system MUST be constructed via this module.
No raw string messages are permitted outside this file.

Functions:
    format_status()          — system state + config snapshot
    format_metrics()         — current metrics snapshot
    format_prelive_check()   — PreLiveValidator structured result
    format_error()           — critical error alert
    format_kill_alert()      — kill switch activated alert
    format_command_response() — generic command acknowledgement
    format_state_change()    — state transition notification
    format_checkpoint()      — periodic pipeline checkpoint summary

Design:
    - Pure functions: no side-effects, no I/O.
    - Every function accepts only primitive types or dicts.
    - All text is Telegram Markdown-compatible (backtick escaping applied).
    - Every function returns a non-empty string.
"""
from __future__ import annotations

import time
from typing import Any, Optional


# ── Helpers ───────────────────────────────────────────────────────────────────


def _ts_utc() -> str:
    """Return a compact UTC timestamp string."""
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _safe(value: Any, width: int = 0) -> str:
    """Convert value to a safe string for Markdown backtick display."""
    s = str(value)
    if width:
        s = s[:width]
    return s


# ── Public formatters ─────────────────────────────────────────────────────────


def format_status(
    state: str,
    reason: str,
    risk_multiplier: float,
    max_position: float,
    mode: str = "",
    extra: Optional[dict] = None,
) -> str:
    """Format a system status message.

    Args:
        state: SystemState value ("RUNNING" | "PAUSED" | "HALTED").
        reason: Most recent state transition reason.
        risk_multiplier: Current risk multiplier (0.0–1.0).
        max_position: Current max position fraction (0.0–0.10).
        mode: Trading mode ("PAPER" | "LIVE"), optional.
        extra: Optional additional key/value pairs to include.

    Returns:
        Formatted Telegram Markdown message string.
    """
    state_emoji = {"RUNNING": "✅", "PAUSED": "⏸️", "HALTED": "🛑"}.get(state.upper(), "❓")
    lines = [
        f"{state_emoji} *SYSTEM STATUS*",
        f"State: `{state}`",
        f"Reason: `{reason}`",
        f"Risk multiplier: `{risk_multiplier:.3f}`",
        f"Max position: `{max_position:.3f}`",
    ]
    if mode:
        lines.append(f"Mode: `{mode}`")
    if extra:
        for k, v in extra.items():
            lines.append(f"{k}: `{_safe(v)}`")
    lines.append(f"_as of {_ts_utc()}_")
    return "\n".join(lines)


def format_metrics(
    data: dict,
    title: str = "METRICS SNAPSHOT",
) -> str:
    """Format a metrics snapshot message.

    Args:
        data: Dict of metric name → value pairs.
        title: Optional section title override.

    Returns:
        Formatted Telegram Markdown message string.
    """
    if not data:
        return f"📈 *{title}*\n_No metrics available._"
    lines = [f"📈 *{title}*"]
    for k, v in data.items():
        if isinstance(v, float):
            lines.append(f"`{k}`: `{v:.4f}`")
        else:
            lines.append(f"`{k}`: `{_safe(v)}`")
    lines.append(f"_as of {_ts_utc()}_")
    return "\n".join(lines)


def format_prelive_check(result: dict) -> str:
    """Format a PreLiveValidator result message.

    Args:
        result: Dict with keys "status", "checks", "reason".
                status: "PASS" | "FAIL"
                checks: dict of check_name → bool
                reason: human-readable failure reason (empty on PASS)

    Returns:
        Formatted Telegram Markdown message string.
    """
    status = str(result.get("status", "UNKNOWN")).upper()
    checks = result.get("checks", {})
    reason = str(result.get("reason", ""))

    status_emoji = "✅" if status == "PASS" else "❌"
    lines = [f"{status_emoji} *PRE-LIVE VALIDATION: {status}*"]

    if checks:
        lines.append("")
        lines.append("*Checks:*")
        for name, passed in checks.items():
            icon = "✅" if passed else "❌"
            label = name.replace("_", " ").title()
            lines.append(f"  {icon} `{label}`")

    if reason and status != "PASS":
        lines.append("")
        lines.append(f"Reason: `{reason}`")

    lines.append(f"_as of {_ts_utc()}_")
    return "\n".join(lines)


def format_error(
    context: str,
    error: str,
    severity: str = "CRITICAL",
    correlation_id: str = "",
) -> str:
    """Format a critical error alert message.

    Args:
        context: Module or operation where the error occurred.
        error: Error message or exception string (truncated to 200 chars).
        severity: Error severity label ("CRITICAL" | "WARNING" | "ERROR").
        correlation_id: Optional request trace ID.

    Returns:
        Formatted Telegram Markdown message string.
    """
    emoji = {"CRITICAL": "🚨", "WARNING": "⚠️", "ERROR": "❌"}.get(severity.upper(), "⚠️")
    lines = [
        f"{emoji} *{severity} ERROR*",
        f"Context: `{_safe(context, 80)}`",
        f"Error: `{_safe(error, 200)}`",
    ]
    if correlation_id:
        lines.append(f"Trace: `{correlation_id[:32]}`")
    lines.append(f"_at {_ts_utc()}_")
    return "\n".join(lines)


def format_kill_alert(
    reason: str,
    correlation_id: str = "",
) -> str:
    """Format a kill switch activated alert.

    Args:
        reason: Human-readable kill switch trigger reason.
        correlation_id: Optional request trace ID.

    Returns:
        Formatted Telegram Markdown message string.
    """
    lines = [
        "🚨 *KILL SWITCH ACTIVATED*",
        f"Reason: `{_safe(reason, 120)}`",
        "All trading halted immediately.",
    ]
    if correlation_id:
        lines.append(f"Trace: `{correlation_id[:32]}`")
    lines.append(f"_at {_ts_utc()}_")
    return "\n".join(lines)


def format_command_response(
    command: str,
    success: bool,
    message: str,
    user_id: str = "",
    payload: Optional[dict] = None,
) -> str:
    """Format a generic command acknowledgement message.

    Args:
        command: Command name that was executed.
        success: Whether the command succeeded.
        message: Human-readable result message.
        user_id: Optional Telegram user ID for attribution.
        payload: Optional structured result data to display.

    Returns:
        Formatted Telegram Markdown message string.
    """
    icon = "✅" if success else "❌"
    lines = [f"{icon} */{command}*", message]
    if user_id:
        lines.append(f"Issued by: `{user_id}`")
    if payload:
        for k, v in list(payload.items())[:5]:
            lines.append(f"  `{k}`: `{_safe(v)}`")
    return "\n".join(lines)


def format_state_change(
    previous: str,
    current: str,
    reason: str,
    initiated_by: str = "system",
) -> str:
    """Format a state transition notification.

    Args:
        previous: Previous SystemState value.
        current: New SystemState value.
        reason: Reason for the transition.
        initiated_by: Who or what triggered the transition.

    Returns:
        Formatted Telegram Markdown message string.
    """
    state_emoji = {"RUNNING": "✅", "PAUSED": "⏸️", "HALTED": "🛑"}.get(current.upper(), "❓")
    lines = [
        f"{state_emoji} *STATE CHANGE*",
        f"Transition: `{previous}` → `{current}`",
        f"Reason: `{_safe(reason, 100)}`",
        f"By: `{initiated_by}`",
        f"_at {_ts_utc()}_",
    ]
    return "\n".join(lines)


def format_checkpoint(
    elapsed_h: float,
    metrics: dict,
    label: str = "",
    correlation_id: str = "",
) -> str:
    """Format a periodic pipeline checkpoint summary.

    Args:
        elapsed_h: Pipeline runtime in hours.
        metrics: Dict of current metric snapshots.
        label: Optional checkpoint label (e.g. "6h", "12h", "24h").
        correlation_id: Optional run/session trace ID.

    Returns:
        Formatted Telegram Markdown message string.
    """
    tag = f" [{label}]" if label else ""
    lines = [
        f"🔵 *CHECKPOINT{tag}*",
        f"Elapsed: `{elapsed_h:.1f}h`",
    ]
    if metrics:
        lines.append("")
        lines.append("*Metrics:*")
        for k, v in metrics.items():
            if isinstance(v, float):
                lines.append(f"  `{k}`: `{v:.4f}`")
            else:
                lines.append(f"  `{k}`: `{_safe(v)}`")
    if correlation_id:
        lines.append(f"Run: `{correlation_id[:32]}`")
    lines.append(f"_at {_ts_utc()}_")
    return "\n".join(lines)


def format_no_signal_alert(
    idle_s: float,
    signal_count: int,
) -> str:
    """Format a no-signal-activity CRITICAL alert.

    Args:
        idle_s: Seconds since the last signal was generated.
        signal_count: Total signals generated so far in this run.

    Returns:
        Formatted Telegram Markdown message string.
    """
    idle_h = idle_s / 3600.0
    lines = [
        "⚠️ *NO SIGNAL ACTIVITY*",
        f"No signal generated in `{idle_h:.1f}h`",
        f"Total signals this run: `{signal_count}`",
        "Check: edge threshold, market liquidity, WS feed.",
        f"_at {_ts_utc()}_",
    ]
    return "\n".join(lines)


def format_no_trade_alert(
    idle_s: float,
    order_count: int,
) -> str:
    """Format a no-trade-activity CRITICAL alert.

    Args:
        idle_s: Seconds since the last simulated order was placed.
        order_count: Total simulated orders placed so far in this run.

    Returns:
        Formatted Telegram Markdown message string.
    """
    idle_h = idle_s / 3600.0
    lines = [
        "⚠️ *NO TRADE ACTIVITY*",
        f"No order placed in `{idle_h:.1f}h`",
        f"Total orders this run: `{order_count}`",
        "Check: signal engine, execution guard, simulator.",
        f"_at {_ts_utc()}_",
    ]
    return "\n".join(lines)


def format_live_mode_activated(
    checks: Optional[dict] = None,
    correlation_id: str = "",
) -> str:
    """Format a LIVE MODE ACTIVATED system alert.

    Sent once when the system successfully transitions to LIVE trading.

    Args:
        checks: Optional dict of pre-live check results (check_name → bool).
        correlation_id: Optional session trace ID.

    Returns:
        Formatted Telegram Markdown message string.
    """
    lines = [
        "🚀 *LIVE MODE ACTIVATED*",
        "PolyQuantBot is now executing REAL trades.",
        "",
        "All pre-live checks passed:",
    ]
    if checks:
        for name, passed in checks.items():
            icon = "✅" if passed else "❌"
            label = name.replace("_", " ").title()
            lines.append(f"  {icon} `{label}`")
    if correlation_id:
        lines.append(f"Session: `{correlation_id[:32]}`")
    lines.append(f"_at {_ts_utc()}_")
    return "\n".join(lines)


def format_real_trade_executed(
    market: str,
    side: str,
    price: float,
    size_usd: float,
    timestamp: int,
    status: str = "filled",
    correlation_id: str = "",
) -> str:
    """Format a REAL TRADE EXECUTED alert.

    Sent after every successful LIVE order execution.

    Args:
        market: Polymarket condition ID (truncated for display).
        side: "YES" | "NO".
        price: Execution price.
        size_usd: Filled size in USD.
        timestamp: Unix epoch milliseconds.
        status: Execution status ("filled" | "partial" | "rejected").
        correlation_id: Optional request trace ID.

    Returns:
        Formatted Telegram Markdown message string.
    """
    status_emoji = {"filled": "💰", "partial": "🟡", "rejected": "❌"}.get(
        status.lower(), "💰"
    )
    lines = [
        f"{status_emoji} *REAL TRADE EXECUTED*",
        f"Market: `{_safe(market, 24)}`",
        f"Side: `{side}`",
        f"Price: `{price:.4f}`",
        f"Size: `${size_usd:.2f}`",
        f"Status: `{status}`",
    ]
    if correlation_id:
        lines.append(f"Trace: `{correlation_id[:32]}`")
    lines.append(f"_at {_ts_utc()}_")
    return "\n".join(lines)


def format_execution_blocked(
    market_id: str,
    reason: str,
    state: str,
    correlation_id: str = "",
) -> str:
    """Format a blocked execution notification.

    Args:
        market_id: Target market condition ID.
        reason: Block reason (from SystemStateManager or gate).
        state: Current system state at time of block.
        correlation_id: Optional request trace ID.

    Returns:
        Formatted Telegram Markdown message string.
    """
    lines = [
        "🔒 *EXECUTION BLOCKED*",
        f"Market: `{_safe(market_id, 24)}`",
        f"State: `{state}`",
        f"Reason: `{_safe(reason, 100)}`",
    ]
    if correlation_id:
        lines.append(f"Trace: `{correlation_id[:32]}`")
    lines.append(f"_at {_ts_utc()}_")
    return "\n".join(lines)
