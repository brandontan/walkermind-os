"""Operator-only admin commands. Requires update.effective_user.id == OPERATOR_CHAT_ID."""
from __future__ import annotations

import logging
import os
import socket
import time
from datetime import datetime, timezone
from typing import Any, Iterable

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ... import audit, notifications
from ...config import get_settings
from ...database import get_pool, is_kill_switch_active, set_kill_switch
from ...domain.ops import job_tracker
from ...domain.ops import kill_switch as ops_kill_switch
from ...users import force_set_tier, get_user_by_username
from ..keyboards import admin_menu
from ..keyboards.admin import ops_dashboard_keyboard
from ..tier import Tier

logger = logging.getLogger(__name__)

# Process boot timestamp — used by the dashboard uptime line. Captured at
# import time so it survives module reloads in long-running deployments
# (Fly.io deploys produce a fresh process anyway, so this is also the
# correct "this machine" timestamp).
_BOOT_MONOTONIC = time.monotonic()


def _is_operator(update: Update) -> bool:
    if update.effective_user is None:
        return False
    return update.effective_user.id == get_settings().OPERATOR_CHAT_ID


# --------------------------------------------------------------------------
# Operator-only gate.
#
# The gate intentionally fails SILENT for non-operators on the new R12f
# commands — replying "Unauthorized" leaks the existence of a privileged
# command surface. The legacy ``admin_root`` / ``allowlist_command``
# replies "⛔ Operator only." for back-compat with their existing UX.
# --------------------------------------------------------------------------

async def _reject_silently(update: Update) -> None:
    """No-op reply for non-operators on R12f commands."""
    if update.callback_query is not None:
        try:
            await update.callback_query.answer()
        except Exception:  # noqa: BLE001 — answer is best-effort
            pass


async def admin_root(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_operator(update) or update.message is None:
        if update.message:
            await update.message.reply_text("⛔ Operator only.")
        return
    active = await is_kill_switch_active()
    await update.message.reply_text(
        f"*⚙️ Admin*\n\nKill switch: {'🔴 ACTIVE' if active else '🟢 inactive'}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=admin_menu(active),
    )


async def admin_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if q is None or not _is_operator(update):
        if q:
            await q.answer("Operator only.", show_alert=True)
        return
    await q.answer()
    sub = (q.data or "").split(":", 1)[-1]

    if sub == "kill":
        active = await is_kill_switch_active()
        await set_kill_switch(not active, reason="operator_toggle",
                              changed_by=None)
        await audit.write(actor_role="operator",
                          action="kill_switch_" + ("on" if not active else "off"))
        await q.message.reply_text(
            f"Kill switch is now *{'ON 🔴' if not active else 'OFF 🟢'}*.",
            parse_mode=ParseMode.MARKDOWN,
        )
    elif sub == "status":
        await _send_status(q.message)
    elif sub == "force_redeem":
        from ...scheduler import redeem_hourly
        await redeem_hourly()
        await q.message.reply_text("✅ Force-redeem run dispatched.")


async def _send_status(message) -> None:
    from ...cache import ping_cache
    from ...database import ping
    pool = get_pool()
    db_ok = await ping()
    cache_ok = await ping_cache()
    async with pool.acquire() as conn:
        users_n = await conn.fetchval("SELECT COUNT(*) FROM users")
        funded_n = await conn.fetchval("SELECT COUNT(*) FROM users WHERE access_tier>=3")
        live_n = await conn.fetchval("SELECT COUNT(*) FROM users WHERE access_tier>=4")
        open_paper = await conn.fetchval(
            "SELECT COUNT(*) FROM positions WHERE status='open' AND mode='paper'")
        open_live = await conn.fetchval(
            "SELECT COUNT(*) FROM positions WHERE status='open' AND mode='live'")
    s = get_settings()
    await message.reply_text(
        "*🩺 System status*\n\n"
        f"DB: {'✅' if db_ok else '❌'}  Cache: {'✅' if cache_ok else '❌'}\n"
        f"Users: {users_n} · Funded: {funded_n} · Live: {live_n}\n"
        f"Open positions: {open_paper} paper · {open_live} live\n\n"
        f"Guards:\n"
        f"  ENABLE_LIVE_TRADING={s.ENABLE_LIVE_TRADING}\n"
        f"  EXECUTION_PATH_VALIDATED={s.EXECUTION_PATH_VALIDATED}\n"
        f"  CAPITAL_MODE_CONFIRMED={s.CAPITAL_MODE_CONFIRMED}\n"
        f"  AUTO_REDEEM_ENABLED={s.AUTO_REDEEM_ENABLED}\n",
        parse_mode=ParseMode.MARKDOWN,
    )


async def allowlist_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_operator(update) or update.message is None:
        if update.message:
            await update.message.reply_text("⛔ Operator only.")
        return
    args = ctx.args or []
    if not args:
        await update.message.reply_text(
            "Usage: `/allowlist @username` or `/allowlist <telegram_user_id> [tier]`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    target = args[0]
    tier = int(args[1]) if len(args) > 1 else Tier.ALLOWLISTED
    user = None
    if target.startswith("@"):
        user = await get_user_by_username(target)
    else:
        try:
            from ...users import get_user_by_telegram_id
            user = await get_user_by_telegram_id(int(target))
        except ValueError:
            user = None
    if user is None:
        await update.message.reply_text(
            f"User {target} not found. They must /start first."
        )
        return
    await force_set_tier(user["id"], tier)
    await audit.write(actor_role="operator", action="allowlist", user_id=user["id"],
                      payload={"new_tier": tier})
    await update.message.reply_text(
        f"✅ {target} promoted to Tier {tier}."
    )
    # Route through notifications.send so the call inherits R12's
    # tenacity retry+backoff and consistent ERROR-on-final-failure logging.
    await notifications.send(
        user["telegram_user_id"],
        f"🎉 You've been promoted to Tier {tier}. New features unlocked!",
    )


# ==========================================================================
# R12f — Operator dashboard, kill switch, jobs, audit log
# ==========================================================================


def _format_uptime(seconds: float) -> str:
    seconds = max(0, int(seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _format_duration_ms(start: datetime | None, end: datetime | None) -> str:
    if start is None or end is None:
        return "—"
    delta = (end - start).total_seconds()
    if delta < 1:
        return f"{int(delta * 1000)}ms"
    if delta < 60:
        return f"{delta:.1f}s"
    return f"{delta / 60:.1f}m"


def _truncate(value: str | None, limit: int) -> str:
    if not value:
        return ""
    return value if len(value) <= limit else value[: max(0, limit - 1)] + "…"


# Telegram's legacy Markdown parser treats ``_ * ` [`` as formatting
# metacharacters. Failed job errors and audit actions routinely contain
# at least underscores (``kill_switch_pause``) and backticks (Python
# repr fragments), which would cause Telegram to reject the whole
# message with a "can't parse entities" error and leave the operator
# blind exactly when something is broken. Escape every dynamic field
# that lands in a MARKDOWN-mode reply.
def _md_escape(text: str | None) -> str:
    if not text:
        return ""
    out = text.replace("\\", "\\\\")
    for ch in ("_", "*", "`", "["):
        out = out.replace(ch, "\\" + ch)
    return out


async def _collect_dashboard_snapshot() -> dict[str, Any]:
    """Pull every datum the operator dashboard needs.

    Each fetch is wrapped so a single broken dependency degrades that
    field to ``None`` rather than crashing the whole snapshot — the
    operator must still get *something* even when the DB is sick.
    """
    snapshot: dict[str, Any] = {
        "uptime_seconds": time.monotonic() - _BOOT_MONOTONIC,
        "hostname": os.environ.get("FLY_MACHINE_ID")
        or os.environ.get("FLY_ALLOC_ID")
        or socket.gethostname(),
        "db_ok": False,
        "active_users": None,
        "open_positions": None,
        "total_usdc": None,
        "auto_trade_users": None,
        # ``None`` = state could not be read. The renderer surfaces this
        # as "❓ unknown" so the operator never sees a misleading
        # "🟢 inactive" during a DB outage (Codex P2 follow-up on
        # PR #874). The risk gate itself fails SAFE on the same error
        # — see ``domain.ops.kill_switch.is_active``.
        "kill_switch_active": None,
        "lock_mode": None,
        "recent_jobs": [],
        "errors": [],
    }
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            snapshot["db_ok"] = await conn.fetchval("SELECT 1") == 1
            snapshot["active_users"] = int(await conn.fetchval(
                "SELECT COUNT(*) FROM users WHERE access_tier >= 2"
            ) or 0)
            snapshot["open_positions"] = int(await conn.fetchval(
                "SELECT COUNT(*) FROM positions WHERE status = 'open'"
            ) or 0)
            snapshot["total_usdc"] = float(await conn.fetchval(
                "SELECT COALESCE(SUM(balance_usdc), 0) FROM wallets"
            ) or 0)
            snapshot["auto_trade_users"] = int(await conn.fetchval(
                "SELECT COUNT(*) FROM users "
                "WHERE auto_trade_on = TRUE AND paused = FALSE"
            ) or 0)
            snapshot["kill_switch_active"] = await ops_kill_switch.is_active(conn)
            snapshot["lock_mode"] = await ops_kill_switch.get_lock_mode(conn)
    except Exception as exc:  # noqa: BLE001 — degrade-not-crash
        logger.error("ops_dashboard snapshot DB read failed: %s", exc)
        snapshot["errors"].append(f"db: {exc}")

    try:
        snapshot["recent_jobs"] = await job_tracker.fetch_recent(limit=3)
    except Exception as exc:  # noqa: BLE001
        logger.error("ops_dashboard recent jobs read failed: %s", exc)
        snapshot["errors"].append(f"jobs: {exc}")

    return snapshot


def _render_dashboard(snapshot: dict[str, Any]) -> str:
    ks = snapshot.get("kill_switch_active")
    if ks is None:
        # Snapshot fetch failed before the kill-switch read — never lie
        # to the operator with "🟢 inactive" in this state.
        kill_state = "❓ unknown (DB unreachable)"
    elif ks:
        kill_state = "🔴 ACTIVE"
    else:
        kill_state = "🟢 inactive"
    lock = " (LOCK)" if snapshot.get("lock_mode") else ""
    db = "✅" if snapshot["db_ok"] else "❌"

    def _val(key: str, fmt=str, default: str = "N/A") -> str:
        v = snapshot.get(key)
        if v is None:
            return default
        try:
            return fmt(v)
        except Exception:
            return default

    lines = [
        "*⚙️ Operator Dashboard*",
        "",
        f"Uptime: {_format_uptime(snapshot['uptime_seconds'])}",
        f"Host:   `{_md_escape(snapshot['hostname'])}`",
        f"DB:     {db}",
        "",
        f"Active users (Tier 2+): {_val('active_users')}",
        f"Open positions:         {_val('open_positions')}",
        f"Total USDC in pool:     "
        f"{_val('total_usdc', lambda v: f'${v:,.2f}')}",
        f"Auto-trade users:       {_val('auto_trade_users')}",
        "",
        f"Kill switch: {kill_state}{lock}",
    ]

    jobs = snapshot.get("recent_jobs") or []
    if jobs:
        lines.append("")
        lines.append("*Recent jobs (last 3):*")
        for j in jobs:
            status = "✅" if j["status"] == "success" else "❌"
            duration = _format_duration_ms(j.get("started_at"),
                                           j.get("finished_at"))
            lines.append(
                f"  {status} `{_md_escape(j['job_name'])}` · {duration}"
            )
    else:
        lines.append("")
        lines.append("_No recent job runs recorded._")

    if snapshot.get("errors"):
        lines.append("")
        # Plain (escaped) text — same legacy-MARKDOWN entity caveat as
        # the /jobs error line above.
        lines.append(
            "Some fields unavailable: "
            + _md_escape("; ".join(snapshot["errors"][:3]))
        )
    return "\n".join(lines)


async def ops_dashboard_command(update: Update,
                                ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """``/ops_dashboard`` — operator-only system snapshot."""
    if not _is_operator(update) or update.message is None:
        await _reject_silently(update)
        return
    snapshot = await _collect_dashboard_snapshot()
    await update.message.reply_text(
        _render_dashboard(snapshot),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=ops_dashboard_keyboard(snapshot["kill_switch_active"]),
    )


async def ops_dashboard_callback(update: Update,
                                 ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the ``ops:`` callback prefix (refresh + quick actions)."""
    q = update.callback_query
    if q is None:
        return
    if not _is_operator(update):
        await _reject_silently(update)
        return
    await q.answer()
    data = q.data or ""
    sub = data.split(":", 2)[1] if ":" in data else ""

    if sub == "refresh":
        snapshot = await _collect_dashboard_snapshot()
        try:
            await q.edit_message_text(
                _render_dashboard(snapshot),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=ops_dashboard_keyboard(snapshot["kill_switch_active"]),
            )
        except Exception:  # noqa: BLE001 — same-content edits raise
            pass
        return

    if sub in ("pause", "resume", "lock"):
        await _apply_killswitch_action(
            sub,
            actor_id=update.effective_user.id if update.effective_user else None,
            reply=q.message.reply_text if q.message else None,
            broadcast_via_ctx=ctx,
        )
        return


# --------------------------------------------------------------------------
# /killswitch
# --------------------------------------------------------------------------

_KS_USAGE = (
    "Usage: `/killswitch <pause|resume|lock>`\n"
    "  pause  — block all new trades (cached 30s before risk gate sees it)\n"
    "  resume — re-open trade flow (clears lock mode)\n"
    "  lock   — pause + force every user's auto_trade_on=false"
)


async def _broadcast_pause(ctx: ContextTypes.DEFAULT_TYPE | None,
                           message: str) -> int:
    """Notify every active auto-trade user that the operator paused trading.

    Returns the number of users we attempted to message. Failures are
    swallowed per-user so one Telegram error never blocks the operator
    flow.
    """
    if ctx is None:
        return 0
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT telegram_user_id FROM users "
                "WHERE auto_trade_on = TRUE OR access_tier >= 2"
            )
    except Exception as exc:  # noqa: BLE001
        logger.error("killswitch broadcast user lookup failed: %s", exc)
        return 0

    sent = 0
    for r in rows:
        try:
            await notifications.send(int(r["telegram_user_id"]), message)
            sent += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "killswitch broadcast send failed user=%s err=%s",
                r["telegram_user_id"], exc,
            )
    return sent


async def _apply_killswitch_action(
    action: str,
    *,
    actor_id: int | None,
    reply,
    broadcast_via_ctx: ContextTypes.DEFAULT_TYPE | None,
) -> None:
    """Shared implementation for ``/killswitch`` and the inline buttons."""
    try:
        result = await ops_kill_switch.set_active(
            action=action, actor_id=actor_id,
        )
    except ValueError as exc:
        if reply is not None:
            await reply(f"❌ {exc}")
        return
    except Exception as exc:  # noqa: BLE001
        logger.error("killswitch %s failed: %s", action, exc)
        if reply is not None:
            await reply(f"❌ killswitch {action} failed: {exc}")
        return

    await audit.write(
        actor_role="operator",
        action=f"kill_switch_{action}",
        payload={"actor_id": actor_id, "result": result},
    )

    if action == "pause":
        if reply is not None:
            await reply(
                "🔴 Kill switch *ACTIVE*. Auto-trade paused (≤30s "
                "propagation). Use `/killswitch resume` to re-open.",
                parse_mode=ParseMode.MARKDOWN,
            )
        await _broadcast_pause(
            broadcast_via_ctx,
            "🛑 Auto-trade paused by operator. New trades are blocked. "
            "Existing positions remain open until you close them.",
        )
    elif action == "resume":
        if reply is not None:
            await reply(
                "🟢 Kill switch deactivated. Auto-trade resumed.",
            )
    elif action == "lock":
        if reply is not None:
            await reply(
                "🔒 Kill switch *LOCKED*. "
                f"{result['users_disabled']} users had auto-trade disabled. "
                "Run `/killswitch resume` after the incident is addressed; "
                "users must re-opt-in individually.",
                parse_mode=ParseMode.MARKDOWN,
            )
        await _broadcast_pause(
            broadcast_via_ctx,
            "🔒 Auto-trade has been locked by the operator due to an "
            "incident. Your auto-trade has been turned OFF — re-enable "
            "from /dashboard once the operator confirms it is safe.",
        )


async def killswitch_command(update: Update,
                             ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """``/killswitch <pause|resume|lock>``."""
    if not _is_operator(update) or update.message is None:
        await _reject_silently(update)
        return
    args: Iterable[str] = ctx.args or []
    args_list = list(args)
    if not args_list:
        await update.message.reply_text(_KS_USAGE,
                                        parse_mode=ParseMode.MARKDOWN)
        return
    action = args_list[0].strip().lower()
    if action not in {"pause", "resume", "lock"}:
        await update.message.reply_text(_KS_USAGE,
                                        parse_mode=ParseMode.MARKDOWN)
        return
    await _apply_killswitch_action(
        action,
        actor_id=update.effective_user.id if update.effective_user else None,
        reply=update.message.reply_text,
        broadcast_via_ctx=ctx,
    )


# --------------------------------------------------------------------------
# /jobs
# --------------------------------------------------------------------------

DEFAULT_JOB_LIMIT = 10
DEFAULT_AUDIT_LIMIT = 20
MAX_OPS_LIMIT = 50


def _parse_limit(args: list[str], default: int) -> tuple[int, bool]:
    """Return ``(limit, only_failed)`` from ``/jobs`` style args.

    ``args`` may be empty, a single integer, the literal ``failed``, or
    both (``failed 5``). Anything else falls back to ``(default, False)``.
    """
    only_failed = False
    limit = default
    for tok in args:
        t = tok.strip().lower()
        if t == "failed":
            only_failed = True
            continue
        try:
            limit = max(1, min(MAX_OPS_LIMIT, int(t)))
        except ValueError:
            continue
    return limit, only_failed


def _render_jobs(rows: list[dict], only_failed: bool) -> str:
    if not rows:
        return ("_No matching job runs._" if only_failed
                else "_No job runs recorded yet._")
    head = "*Recent failed job runs*" if only_failed else "*Recent job runs*"
    lines = [head, ""]
    for r in rows:
        status = "✅" if r["status"] == "success" else "❌"
        ts = r["started_at"].strftime("%m-%d %H:%M:%S") \
            if r.get("started_at") else "—"
        duration = _format_duration_ms(r.get("started_at"),
                                       r.get("finished_at"))
        err = _truncate(r.get("error"), 80)
        line = (f"{status} `{_md_escape(r['job_name'])}` · "
                f"{ts} · {duration}")
        if err:
            # Render the error as plain (escaped) text — legacy
            # ParseMode.MARKDOWN does NOT honour backslash escapes
            # inside an entity span, so wrapping the escaped err in
            # ``_..._`` could still fail to parse on common error
            # strings (Codex follow-up review on PR #874).
            line += f"\n    └ {_md_escape(err)}"
        lines.append(line)
    return "\n".join(lines)


async def jobs_command(update: Update,
                       ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """``/jobs [n] [failed]`` — last N (default 10) scheduler runs."""
    if not _is_operator(update) or update.message is None:
        await _reject_silently(update)
        return
    limit, only_failed = _parse_limit(list(ctx.args or []), DEFAULT_JOB_LIMIT)
    try:
        rows = await job_tracker.fetch_recent(
            limit=limit, only_failed=only_failed,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("/jobs query failed: %s", exc)
        await update.message.reply_text(f"❌ /jobs query failed: {exc}")
        return
    await update.message.reply_text(
        _render_jobs(rows, only_failed), parse_mode=ParseMode.MARKDOWN,
    )


# --------------------------------------------------------------------------
# /auditlog
# --------------------------------------------------------------------------

async def _fetch_audit_tail(limit: int) -> list[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT ts, actor_role, action, user_id "
            "FROM audit.log ORDER BY ts DESC LIMIT $1",
            limit,
        )
    return [dict(r) for r in rows]


def _render_auditlog(rows: list[dict]) -> str:
    if not rows:
        return "_Audit log is empty._"
    lines = ["*Audit log (most recent first)*", ""]
    for r in rows:
        ts = (r["ts"].astimezone(timezone.utc).strftime("%m-%d %H:%M:%S")
              if r.get("ts") else "—")
        user = _truncate(str(r.get("user_id") or ""), 8)
        actor = r.get("actor_role") or "?"
        action = _truncate(r.get("action"), 40)
        lines.append(
            f"`{ts}` · {_md_escape(actor)} · {_md_escape(action)} · "
            f"{_md_escape(user) or '—'}"
        )
    return "\n".join(lines)


async def auditlog_command(update: Update,
                           ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """``/auditlog [n]`` — last N (default 20) audit.log rows. Read-only."""
    if not _is_operator(update) or update.message is None:
        await _reject_silently(update)
        return
    limit, _ = _parse_limit(list(ctx.args or []), DEFAULT_AUDIT_LIMIT)
    try:
        rows = await _fetch_audit_tail(limit)
    except Exception as exc:  # noqa: BLE001
        logger.error("/auditlog query failed: %s", exc)
        await update.message.reply_text(f"❌ /auditlog query failed: {exc}")
        return
    await update.message.reply_text(
        _render_auditlog(rows), parse_mode=ParseMode.MARKDOWN,
    )
