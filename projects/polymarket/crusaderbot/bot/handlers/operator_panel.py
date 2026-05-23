"""Consolidated operator control panel — ``/panel``.

A single operator-only inline-keyboard surface that composes the controls and
views CrusaderBot already exposes piecemeal (kill switch, ops dashboard, job
runs) into one panel: Start / Stop / Lock / Status / Stats / Settings / Help.

This module owns NO control logic of its own — Start/Stop/Lock delegate to
``admin._apply_killswitch_action`` (the single kill-switch path), Status reuses
``admin._collect_dashboard_snapshot``, and Stats reads the durable scan-pipeline
metrics from ``job_runs.metadata`` via ``job_tracker.fetch_latest``. Access is
gated to ``OPERATOR_CHAT_ID`` via ``admin._is_operator``. Paper-mode only — it
surfaces guard flags read-only and never opens the live-trading gate.
"""
from __future__ import annotations

import html
import json
import logging
from typing import Any

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ...config import get_settings, resolve_trading_mode
from ...domain.ops import job_tracker
from ...domain.ops import kill_switch as ops_kill_switch
from ..keyboards.admin import operator_panel_keyboard
from .admin import (
    _apply_killswitch_action,
    _collect_dashboard_snapshot,
    _is_operator,
    _reject_silently,
    _render_dashboard,
)

logger = logging.getLogger(__name__)


def _resolve_mode() -> str:
    """Paper/live label — delegates to the canonical ``config.resolve_trading_mode``."""
    return resolve_trading_mode()


def _coerce_metadata(raw: Any) -> dict[str, Any]:
    """Decode a ``job_runs.metadata`` value to a dict.

    asyncpg returns the JSONB column as a ``str`` (no codec is registered),
    so we json.loads strings; dicts pass through; anything else -> ``{}``.
    """
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw:
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


async def _render_root() -> str:
    mode = _resolve_mode()
    try:
        active = await ops_kill_switch.is_active()
        lock = await ops_kill_switch.get_lock_mode()
    except Exception as exc:  # noqa: BLE001 — UI degrades, never 5xx the panel
        logger.error("panel root: kill switch read failed: %s", exc)
        active, lock = None, False
    if active is None:
        run_state = "❓ unknown (DB unreachable)"
    elif active:
        run_state = "⏹ STOPPED (kill switch ACTIVE)" + (" 🔒 LOCK" if lock else "")
    else:
        run_state = "▶️ RUNNING"
    return (
        "<b>🎛 Operator Control Panel</b>\n\n"
        f"Mode: <b>{html.escape(mode.upper())}</b>\n"
        f"State: {run_state}\n\n"
        "Start / Stop the auto-trade engine, or open Status / Stats below."
    )


def _render_stats(scan_md: dict[str, Any], snap_md: dict[str, Any]) -> str:
    def g(md: dict[str, Any], key: str, default: str = "N/A") -> str:
        v = md.get(key)
        return default if v is None else html.escape(str(v))

    strategies = scan_md.get("strategies_loaded")
    strategies_str = (
        ", ".join(html.escape(str(s)) for s in strategies)
        if isinstance(strategies, list) and strategies else "N/A"
    )
    return (
        "<b>📈 Scan Pipeline Stats</b>\n"
        "<i>(latest signal_scan tick)</i>\n\n"
        f"Mode: <b>{g(scan_md, 'mode')}</b>  ·  live_trading: {g(scan_md, 'live_trading')}\n"
        f"Strategies loaded: {strategies_str}\n"
        f"Users scanned: {g(scan_md, 'users_scanned')}\n"
        f"Markets seen: {g(scan_md, 'markets_seen')}\n"
        f"Candidates emitted: {g(scan_md, 'candidates_emitted')}\n"
        f"Risk approved: {g(scan_md, 'risk_approved')}  ·  rejected: {g(scan_md, 'risk_rejected')}\n"
        f"Paper orders created: {g(scan_md, 'paper_orders_created')}\n"
        f"Positions created: {g(scan_md, 'positions_created')}\n"
        f"Errors: {g(scan_md, 'errors')}\n\n"
        f"Snapshots written: {g(snap_md, 'snapshots_written')}"
    )


def _render_settings() -> str:
    s = get_settings()
    return (
        "<b>⚙️ Settings (read-only)</b>\n\n"
        "<b>Guards:</b>\n"
        f"  ENABLE_LIVE_TRADING={s.ENABLE_LIVE_TRADING}\n"
        f"  EXECUTION_PATH_VALIDATED={s.EXECUTION_PATH_VALIDATED}\n"
        f"  CAPITAL_MODE_CONFIRMED={s.CAPITAL_MODE_CONFIRMED}\n"
        f"  AUTO_REDEEM_ENABLED={s.AUTO_REDEEM_ENABLED}\n\n"
        "<b>Scan intervals (s):</b>\n"
        f"  signal_scan={s.SIGNAL_SCAN_INTERVAL}\n"
        f"  exit_watch={s.EXIT_WATCH_INTERVAL}\n"
        f"  portfolio_snapshots={s.PORTFOLIO_SNAPSHOT_INTERVAL}\n"
        f"  market_sync={s.MARKET_SCAN_INTERVAL}\n\n"
        "<i>Live-enable is gated behind /live_checklist — not changeable here.</i>"
    )


_HELP_TEXT = (
    "<b>❓ Operator Panel — Help</b>\n\n"
    "▶️ <b>Start</b> — release the kill switch (auto-trade resumes).\n"
    "⏹ <b>Stop</b> — engage the kill switch (blocks new trades; open positions stay).\n"
    "🔒 <b>Lock</b> — Stop + force every user's auto-trade OFF (incident use).\n"
    "📊 <b>Status</b> — live system snapshot (DB, users, positions, pool, guards).\n"
    "📈 <b>Stats</b> — latest scan-pipeline metrics from the last signal_scan tick.\n"
    "⚙️ <b>Settings</b> — read-only guard flags + scan intervals.\n"
    "🔄 <b>Refresh</b> — re-render this panel.\n\n"
    "Paper mode only. Existing commands /killswitch, /ops_dashboard, /jobs still work."
)


async def panel_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """``/panel`` — operator-only consolidated control panel."""
    if not _is_operator(update) or update.message is None:
        await _reject_silently(update)
        return
    try:
        active = await ops_kill_switch.is_active()
    except Exception as exc:  # noqa: BLE001 — panel must still open during a DB hiccup
        logger.error("panel command: kill switch read failed: %s", exc)
        active = False
    await update.message.reply_text(
        await _render_root(),
        parse_mode=ParseMode.HTML,
        reply_markup=operator_panel_keyboard(active),
    )


async def _edit(q, text: str) -> None:
    try:
        active = await ops_kill_switch.is_active()
    except Exception as exc:  # noqa: BLE001
        logger.error("panel edit: kill switch read failed: %s", exc)
        active = False
    try:
        await q.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=operator_panel_keyboard(active),
        )
    except Exception as exc:  # noqa: BLE001
        # Telegram raises BadRequest("message is not modified") when the operator
        # re-taps a view that is already showing — a benign no-op we suppress at
        # debug; anything else is a real edit failure and must surface in logs.
        if "message is not modified" in str(exc).lower():
            logger.debug("panel edit skipped (not modified): %s", exc)
            return
        logger.error("panel edit failed: %s", exc)


async def panel_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the ``panel:`` callback prefix."""
    q = update.callback_query
    if q is None:
        return
    if not _is_operator(update):
        await _reject_silently(update)
        return
    await q.answer()
    sub = (q.data or "").split(":", 1)[-1]

    if sub in ("start", "stop", "lock"):
        action = {"start": "resume", "stop": "pause", "lock": "lock"}[sub]
        await _apply_killswitch_action(
            action,
            actor_id=update.effective_user.id if update.effective_user else None,
            reply=q.message.reply_text if q.message else None,
            broadcast_via_ctx=ctx,
        )
        await _edit(q, await _render_root())
        return

    if sub == "status":
        snapshot = await _collect_dashboard_snapshot()
        await _edit(q, _render_dashboard(snapshot))
        return

    if sub == "stats":
        try:
            scan_row = await job_tracker.fetch_latest("signal_scan")
            snap_row = await job_tracker.fetch_latest("portfolio_snapshots")
        except Exception as exc:  # noqa: BLE001
            logger.error("panel stats: job_tracker read failed: %s", exc)
            await _edit(q, "<b>📈 Scan Pipeline Stats</b>\n\nN/A — data not available.")
            return
        scan_md = _coerce_metadata(scan_row.get("metadata")) if scan_row else {}
        snap_md = _coerce_metadata(snap_row.get("metadata")) if snap_row else {}
        await _edit(q, _render_stats(scan_md, snap_md))
        return

    if sub == "settings":
        await _edit(q, _render_settings())
        return

    if sub == "help":
        await _edit(q, _HELP_TEXT)
        return

    if sub == "refresh":
        await _edit(q, await _render_root())
        return
