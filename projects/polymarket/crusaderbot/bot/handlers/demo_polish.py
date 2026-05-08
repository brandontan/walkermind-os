"""Investor-facing demo polish commands: /about, /status, /demo.

These three commands form the demo surface for CrusaderBot — investor-friendly
copy, no internal jargon, no activation-guard mutations, all read-only.

  /about   — static investor-friendly description; explicitly states paper
             mode is the current posture.
  /status  — calls ``monitoring.health.run_health_checks()`` directly (no
             in-process HTTP self-call) and renders the demo-readiness payload
             alongside a 📄 PAPER MODE / ⚡ LIVE MODE indicator. Pulls mode +
             version + uptime via the same helpers that back GET /health so
             both surfaces report identically.
  /demo    — read-only top-3 preview of recent signal_publications. Per-user
             rate limit: 1 invocation per 60 seconds. Never executes orders,
             never calls the risk gate, never inserts into execution_queue.

Rate limit:
    Module-level dict keyed by ``telegram_user_id`` -> last-call monotonic
    timestamp. python-telegram-bot dispatches commands on a single asyncio
    loop, so a plain dict is race-free. Module reload (test isolation) clears
    state via ``_reset_demo_rate_limit_for_tests``.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ...api.health import _resolve_mode, _resolve_version, _uptime_seconds
from ...database import get_pool
from ...monitoring.health import run_health_checks

logger = logging.getLogger(__name__)

DEMO_RATE_LIMIT_SECONDS: float = 60.0
_DEMO_LAST_CALL: dict[int, float] = {}


def _now() -> float:
    """Indirection seam for tests — patching ``time.monotonic`` directly
    leaks into the asyncio event loop's internal clock and crashes the
    runner. Tests patch this function instead.
    """
    return time.monotonic()


def _reset_demo_rate_limit_for_tests() -> None:
    """Test-only hook: clear the per-user rate-limit timestamps."""
    _DEMO_LAST_CALL.clear()


# ---------------------------------------------------------------------------
# /about
# ---------------------------------------------------------------------------

_ABOUT_TEXT = (
    "*⚔️ About CrusaderBot*\n\n"
    "CrusaderBot is an autonomous trading service for Polymarket, "
    "controlled entirely through Telegram. Users configure their "
    "strategy preferences and risk profile; the bot scans markets, "
    "manages entries and exits, and auto-redeems winning positions.\n\n"
    "*How it works*\n"
    "• You pick a strategy (copy a wallet, follow a curated signal feed).\n"
    "• You set a risk profile (Conservative / Balanced / Aggressive).\n"
    "• The bot watches markets and executes trades on your behalf, "
    "always within hard-wired risk limits.\n"
    "• You stay in control — pause, close, or withdraw at any time.\n\n"
    "*Safety posture*\n"
    "📄 *Paper-trading mode is the default.* Live trading requires "
    "explicit operator activation across multiple guards.\n"
    "• Hard daily-loss stop and max-drawdown circuit breaker.\n"
    "• Fractional Kelly sizing capped at 25% — never full Kelly.\n"
    "• Independent kill switch reachable over Telegram.\n\n"
    "*Try it now*\n"
    "• /demo — preview the live signals the bot is watching.\n"
    "• /status — see the current health and trading mode.\n"
    "• /help — full command reference.\n"
)


async def about_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    await update.message.reply_text(
        _ABOUT_TEXT, parse_mode=ParseMode.MARKDOWN,
    )


# ---------------------------------------------------------------------------
# /status
# ---------------------------------------------------------------------------


def _format_uptime(seconds: int) -> str:
    """Friendly uptime: ``2d 4h 30m`` / ``3h 12m`` / ``2m`` / ``0m``."""
    seconds = max(0, int(seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _check_emoji(state: str) -> str:
    return {
        "ok": "🟢",
        "degraded": "🟡",
        "down": "🔴",
        "unknown": "⚪️",
    }.get(state, "⚪️")


def _format_status(health: dict[str, Any], mode: str, version: str,
                   uptime_s: int) -> str:
    mode_banner = (
        "📄 *PAPER MODE* — no real capital at risk"
        if mode == "paper"
        else "⚡ *LIVE MODE* — real capital is deployed"
    )
    overall_emoji = _check_emoji(health.get("status", "unknown"))
    overall = (health.get("status") or "unknown").upper()
    ready = "✅ ready" if health.get("ready") else "⚠️ not ready"
    checks = health.get("checks") or {}
    checks_block = "\n".join(
        f"  {_check_emoji(state)} `{name}` — {state}"
        for name, state in sorted(checks.items())
    ) or "  _(no dependency checks reported)_"
    # Demo phase line: derived from mode + ready, not invented.
    if mode == "paper" and health.get("ready"):
        phase_line = "Closed-beta build • paper trading active"
    elif mode == "paper":
        phase_line = "Closed-beta build • paper trading (degraded)"
    else:
        phase_line = "Live trading active"
    return (
        f"{mode_banner}\n\n"
        f"*Overall:* {overall_emoji} {overall} — {ready}\n"
        f"*Phase:* {phase_line}\n"
        f"*Version:* `{version}`\n"
        f"*Uptime:* {_format_uptime(uptime_s)}\n\n"
        f"*Dependency checks*\n{checks_block}"
    )


async def status_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    try:
        health = await run_health_checks()
    except Exception as exc:  # noqa: BLE001 — surface as friendly error
        logger.warning("status_health_check_failed", exc_info=exc)
        await update.message.reply_text(
            "📄 *PAPER MODE*\n\n"
            "Health check is temporarily unavailable. Try again in a moment.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    text = _format_status(
        health=health,
        mode=_resolve_mode(),
        version=_resolve_version(),
        uptime_s=_uptime_seconds(),
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# ---------------------------------------------------------------------------
# /demo
# ---------------------------------------------------------------------------

# Read top-3 most-recent active entry signals across active feeds. Joins
# markets so the question text is investor-readable. Filters out exit
# signals and expired publications.
_RECENT_SIGNALS_SQL = """
    SELECT
        sf.name              AS feed_name,
        sp.market_id         AS market_id,
        sp.side              AS side,
        sp.target_price      AS target_price,
        sp.payload           AS payload,
        sp.published_at      AS published_at,
        m.question           AS market_question
    FROM signal_publications sp
    JOIN signal_feeds        sf ON sf.id = sp.feed_id
    LEFT JOIN markets        m  ON m.id = sp.market_id
    WHERE sp.exit_signal = FALSE
      AND (sp.expires_at IS NULL OR sp.expires_at > NOW())
      AND sp.exit_published_at IS NULL
      AND sf.status = 'active'
    ORDER BY sp.published_at DESC
    LIMIT 3
"""


def _payload_dict(raw: Any) -> dict[str, Any]:
    """Coerce a publication ``payload`` column value into a plain dict.

    asyncpg returns JSONB as a Python ``str`` by default unless a JSON codec
    is registered on the connection. Both the str path and the (already
    decoded) dict path are handled so this module is decoupled from the
    pool setup. Mirrors ``services.signal_feed.signal_evaluator._payload_dict``
    so the two surfaces agree on what an unparseable payload looks like
    (``{}``).
    """
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw:
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _extract_confidence(payload: Any) -> str:
    """Pull a 0..1 confidence from the publication payload, format as %.

    The publication ``payload`` JSONB is operator-defined. Three common keys
    are accepted (``confidence`` / ``edge`` / ``score``); anything else is
    rendered as an em-dash so the demo never invents data. JSON strings
    (asyncpg without a JSON codec) are parsed via ``_payload_dict`` first.
    """
    payload_d = _payload_dict(payload)
    for key in ("confidence", "edge", "score"):
        v = payload_d.get(key)
        if isinstance(v, (int, float)) and 0.0 <= float(v) <= 1.0:
            return f"{float(v) * 100:.0f}%"
    return "—"


# Telegram Markdown (V1) metacharacters. Operator / DB-supplied strings flow
# through ``ParseMode.MARKDOWN``, so an unbalanced ``_`` or stray backtick
# causes Telegram to reject the entire message — escape before interpolation.
_MARKDOWN_METACHARS = ("_", "*", "`", "[")


def _escape_md(text: str | None) -> str:
    """Escape Telegram Markdown V1 metacharacters in DB-supplied text.

    Same shape as ``bot.handlers.signal_following._escape_md`` so both
    investor surfaces handle operator-supplied feed names + market
    questions identically. Backslash is escaped first so the metachar
    loop does not double-escape.
    """
    if not text:
        return ""
    out = text.replace("\\", "\\\\")
    for ch in _MARKDOWN_METACHARS:
        out = out.replace(ch, "\\" + ch)
    return out


def _truncate(s: str, limit: int = 80) -> str:
    s = (s or "").strip()
    if len(s) <= limit:
        return s
    return s[: limit - 1] + "…"


def _format_demo(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return (
            "*🔍 Demo signal scan*\n\n"
            "📄 _Paper mode_ — no active signals are currently published.\n\n"
            "Once operators publish signals to active feeds, the top three "
            "will appear here."
        )
    lines = ["*🔍 Demo signal scan — top 3 live signals*\n"]
    for i, row in enumerate(rows, start=1):
        # DB-derived strings (market_question, feed_name) flow into a
        # ParseMode.MARKDOWN reply — escape after truncate so the ellipsis
        # math operates on visible characters, not escape sequences.
        question = _escape_md(
            _truncate(str(row.get("market_question") or row.get("market_id") or "—"))
        )
        side = (row.get("side") or "—").upper()
        feed = _escape_md(
            _truncate(str(row.get("feed_name") or "—"), limit=24)
        )
        confidence = _extract_confidence(row.get("payload"))
        target = row.get("target_price")
        target_str = f"{float(target):.2f}" if isinstance(target, (int, float)) else "—"
        lines.append(
            f"*{i}.* {question}\n"
            f"   • Side: *{side}*  • Confidence: *{confidence}*  • Target: *{target_str}*\n"
            f"   • Feed: _{feed}_"
        )
    lines.append(
        "\n_📄 Paper mode — these signals are observed only; no orders are placed._"
    )
    return "\n".join(lines)


async def _fetch_recent_signals() -> list[dict[str, Any]]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(_RECENT_SIGNALS_SQL)
    return [dict(r) for r in rows]


async def demo_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return
    user_id = update.effective_user.id
    now = _now()
    last = _DEMO_LAST_CALL.get(user_id)
    if last is not None and (now - last) < DEMO_RATE_LIMIT_SECONDS:
        wait = int(DEMO_RATE_LIMIT_SECONDS - (now - last))
        await update.message.reply_text(
            f"⏳ /demo is rate-limited — try again in {max(1, wait)}s.",
        )
        return
    _DEMO_LAST_CALL[user_id] = now

    try:
        rows = await _fetch_recent_signals()
    except Exception as exc:  # noqa: BLE001 — graceful empty-state on failure
        logger.warning("demo_fetch_signals_failed", exc_info=exc)
        rows = []
    await update.message.reply_text(
        _format_demo(rows), parse_mode=ParseMode.MARKDOWN,
    )


__all__ = [
    "about_command",
    "status_command",
    "demo_command",
    "DEMO_RATE_LIMIT_SECONDS",
    "_reset_demo_rate_limit_for_tests",
]
