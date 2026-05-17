"""Admin-only commands. Caller must be the admin (OPERATOR_CHAT_ID) or hold
the ADMIN role. OPERATOR_CHAT_ID is infrastructure (alert routing + root
admin), not a user-facing role."""
from __future__ import annotations

import html
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
from ...services.tiers import (
    TIER_ADMIN,
    VALID_TIERS,
    get_user_tier,
    list_all_user_tiers,
    set_user_tier,
)
from ...users import (
    force_set_tier, get_user_by_telegram_id, get_user_by_username,
    set_auto_trade, set_onboarding_complete, update_settings,
)
from ..keyboards import admin_menu
from ..keyboards.admin import ops_dashboard_keyboard

logger = logging.getLogger(__name__)

_BOOT_MONOTONIC = time.monotonic()


def _is_operator(update: Update) -> bool:
    if update.effective_user is None:
        return False
    return update.effective_user.id == get_settings().OPERATOR_CHAT_ID


async def _reject_silently(update: Update) -> None:
    """No-op reply for non-operators on R12f commands."""
    if update.callback_query is not None:
        try:
            await update.callback_query.answer()
        except Exception:  # noqa: BLE001
            pass


# Two-role model: 'user' / 'admin'. Mapped onto the underlying tier
# column (which the DB CHECK constraint still pins to FREE/ADMIN) so no
# migration is required. Legacy FREE/PREMIUM/ADMIN are still accepted.
_ROLE_MAP = {"USER": "FREE", "ADMIN": "ADMIN"}

_ADMIN_HELP = (
    "<b>🛠 Admin</b>\n\n"
    "• Runtime Health — /ops_dashboard, /health\n"
    "• User Monitor — /admin users, /admin stats\n"
    "• Emergency Stop — /kill, /resume, /killswitch\n"
    "• Logs — /auditlog, /jobs\n"
    "• Roles — /admin settier {user_id} {user|admin}\n"
    "• Broadcast — /admin broadcast {message}\n"
    "• /resetonboard {telegram_user_id} — reset onboarding for testing"
)


async def _is_admin_user(update: Update) -> bool:
    """Return True if the caller is the operator OR holds ADMIN tier."""
    if _is_operator(update):
        return True
    if update.effective_user is None:
        return False
    tier = await get_user_tier(update.effective_user.id)
    return tier == TIER_ADMIN


async def admin_root(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    is_op = _is_operator(update)
    if not is_op:
        if not await _is_admin_user(update):
            await update.message.reply_text("Admin access required.")
            return

    args = list(ctx.args or [])

    if args:
        sub = args[0].lower()
        actor_id = (update.effective_user.id
                    if update.effective_user else 0)
        if sub == "users":
            await _admin_users(update.message)
        elif sub == "settier":
            await _admin_settier(update.message, args[1:], actor_id)
        elif sub == "stats":
            await _admin_stats(update.message)
        elif sub == "broadcast":
            await _admin_broadcast(update.message, args[1:], ctx)
        else:
            await update.message.reply_text(
                _ADMIN_HELP, parse_mode=ParseMode.HTML
            )
        return

    if is_op:
        active = await is_kill_switch_active()
        ks_label = "🔴 ACTIVE" if active else "🟢 inactive"
        await update.message.reply_text(
            f"<b>⚙️ Admin</b>\n\nKill switch: {ks_label}",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_menu(active),
        )
    else:
        await update.message.reply_text(
            _ADMIN_HELP, parse_mode=ParseMode.HTML
        )


async def _admin_users(message) -> None:
    rows = await list_all_user_tiers(limit=50)
    if not rows:
        await message.reply_text("No users in user_tiers table yet.",
                                 parse_mode=ParseMode.HTML)
        return
    lines = ["<b>Users + Tiers</b> (most recent first)\n"]
    for r in rows:
        ts = r["assigned_at"].strftime("%m-%d %H:%M") if r.get("assigned_at") else "—"
        lines.append(f"<code>{r['user_id']}</code> — <b>{r['tier']}</b> (set {ts})")
    await message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def _admin_settier(message, args: list[str], actor_id: int) -> None:
    if len(args) < 2:
        await message.reply_text(
            "Usage: <code>/admin settier {user_id} {user|admin}</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    raw_uid, raw_tier = args[0], args[1].upper()
    try:
        target_uid = int(raw_uid)
    except ValueError:
        await message.reply_text(
            f"Invalid user_id: <code>{html.escape(raw_uid)}</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    raw_tier = _ROLE_MAP.get(raw_tier, raw_tier)
    if raw_tier not in VALID_TIERS:
        await message.reply_text(
            f"Invalid role <code>{html.escape(args[1])}</code>. Valid: user, admin",
            parse_mode=ParseMode.HTML,
        )
        return
    await set_user_tier(target_uid, raw_tier, assigned_by=actor_id)
    await audit.write(
        actor_role="admin",
        action="settier",
        payload={"target_user_id": target_uid, "tier": raw_tier,
                 "assigned_by": actor_id},
    )
    role_label = "admin" if raw_tier == "ADMIN" else "user"
    await message.reply_text(
        f"✅ User <code>{target_uid}</code> set to <b>{role_label}</b>.",
        parse_mode=ParseMode.HTML,
    )


async def _admin_stats(message) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users") or 0
        open_positions = await conn.fetchval(
            "SELECT COUNT(*) FROM positions WHERE status='open'"
        ) or 0
        paper_pnl = await conn.fetchval(
            "SELECT COALESCE(SUM(pnl_usdc), 0) FROM positions WHERE mode='paper'"
        ) or 0.0
        free_n = await conn.fetchval(
            "SELECT COUNT(*) FROM users u "
            "LEFT JOIN user_tiers ut ON ut.user_id = u.telegram_user_id "
            "WHERE ut.tier IS NULL OR ut.tier = 'FREE'"
        ) or 0
        premium_n = await conn.fetchval(
            "SELECT COUNT(*) FROM user_tiers WHERE tier='PREMIUM'"
        ) or 0
        admin_n = await conn.fetchval(
            "SELECT COUNT(*) FROM user_tiers WHERE tier='ADMIN'"
        ) or 0
    await message.reply_text(
        "<b>📊 Admin Stats</b>\n\n"
        f"Total users: {total_users}\n"
        f"Roles — Users: {free_n + premium_n} · Admins: {admin_n}\n"
        f"Open positions: {open_positions}\n"
        f"Paper PNL (all time): ${float(paper_pnl):+,.2f}",
        parse_mode=ParseMode.HTML,
    )


async def _admin_broadcast(message, args: list[str], ctx) -> None:
    if not args:
        await message.reply_text(
            "Usage: <code>/admin broadcast {message}</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    text = " ".join(args)
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT telegram_user_id FROM users")
    sent = 0
    failed = 0
    for r in rows:
        try:
            ok = await notifications.send(int(r["telegram_user_id"]), text)
            if ok:
                sent += 1
            else:
                failed += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("broadcast send failed user=%s err=%s",
                           r["telegram_user_id"], exc)
            failed += 1
    await message.reply_text(
        f"✅ Broadcast sent: {sent} delivered, {failed} failed."
    )


async def resetonboard_command(update: Update,
                               ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Reset onboarding state for a user. Admin/operator only."""
    if update.message is None:
        return
    if not await _is_admin_user(update):
        await update.message.reply_text("Admin access required.")
        return
    args = ctx.args or []
    if not args:
        await update.message.reply_text(
            "Usage: <code>/resetonboard {telegram_user_id}</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    try:
        tg_uid = int(args[0])
    except ValueError:
        await update.message.reply_text(
            "Invalid telegram_user_id — must be an integer."
        )
        return
    user = await get_user_by_telegram_id(tg_uid)
    if user is None:
        await update.message.reply_text("User not found.")
        return
    await set_onboarding_complete(user["id"], False)
    await set_auto_trade(user["id"], False)
    await update_settings(user["id"], active_preset=None, strategy_types=[])
    uname = html.escape(user.get("username") or str(tg_uid))
    await update.message.reply_text(
        f"Onboarding reset for @{uname} (tg:{tg_uid}). "
        "Next /start triggers full concierge flow.",
        parse_mode=ParseMode.HTML,
    )
    await audit.write(
        actor_role="admin",
        action="resetonboard",
        payload={"target_tg_id": tg_uid},
    )


async def admin_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if q is None or not _is_operator(update):
        if q:
            await q.answer("Admin access required.", show_alert=True)
        return
    await q.answer()
    sub = (q.data or "").split(":", 1)[-1]

    if sub == "kill":
        active = await is_kill_switch_active()
        await set_kill_switch(not active, reason="operator_toggle",
                              changed_by=None)
        await audit.write(actor_role="operator",
                          action="kill_switch_" + ("on" if not active else "off"))
        ks_now = "ON 🔴" if not active else "OFF 🟢"
        await q.message.reply_text(
            f"Kill switch is now <b>{ks_now}</b>.",
            parse_mode=ParseMode.HTML,
        )
    elif sub == "status":
        await _send_status(q.message)
    elif sub == "force_redeem":
        from ...scheduler import redeem_hourly
        await redeem_hourly()
        await q.message.reply_text("✅ Force-redeem run dispatched.")
    elif sub == "resetonboard_prompt":
        await q.message.reply_text(
            "To reset onboarding, use:\n"
            "<code>/resetonboard {telegram_user_id}</code>",
            parse_mode=ParseMode.HTML,
        )


async def _send_status(message) -> None:
    from ...cache import ping_cache
    from ...database import ping
    pool = get_pool()
    db_ok = await ping()
    cache_ok = await ping_cache()
    async with pool.acquire() as conn:
        users_n = await conn.fetchval("SELECT COUNT(*) FROM users")
        admin_n = await conn.fetchval("SELECT COUNT(*) FROM user_tiers WHERE tier='ADMIN'")
        open_paper = await conn.fetchval(
            "SELECT COUNT(*) FROM positions WHERE status='open' AND mode='paper'")
        open_live = await conn.fetchval(
            "SELECT COUNT(*) FROM positions WHERE status='open' AND mode='live'")
    s = get_settings()
    await message.reply_text(
        "<b>🩺 System status</b>\n\n"
        f"DB: {'✅' if db_ok else '❌'}  Cache: {'✅' if cache_ok else '❌'}\n"
        f"Users: {users_n} · Admins: {admin_n}\n"
        f"Open positions: {open_paper} paper · {open_live} live\n\n"
        f"Guards:\n"
        f"  ENABLE_LIVE_TRADING={s.ENABLE_LIVE_TRADING}\n"
        f"  EXECUTION_PATH_VALIDATED={s.EXECUTION_PATH_VALIDATED}\n"
        f"  CAPITAL_MODE_CONFIRMED={s.CAPITAL_MODE_CONFIRMED}\n"
        f"  AUTO_REDEEM_ENABLED={s.AUTO_REDEEM_ENABLED}\n",
        parse_mode=ParseMode.HTML,
    )


async def allowlist_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_operator(update) or update.message is None:
        if update.message:
            await update.message.reply_text("Admin access required.")
        return
    args = ctx.args or []
    if not args:
        await update.message.reply_text(
            "Usage: <code>/allowlist @username</code> or "
            "<code>/allowlist &lt;telegram_user_id&gt; [tier]</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    target = args[0]
    tier = int(args[1]) if len(args) > 1 else 2
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
    await update.message.reply_text(f"✅ {target} access updated by admin.")
    await notifications.send(
        user["telegram_user_id"],
        "✅ Your access has been updated by an admin.",
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


async def _collect_dashboard_snapshot() -> dict[str, Any]:
    """Pull every datum the operator dashboard needs."""
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
                "SELECT COUNT(*) FROM users"
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
    except Exception as exc:  # noqa: BLE001
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
        "<b>⚙️ Admin Dashboard</b>",
        "",
        f"Uptime: {_format_uptime(snapshot['uptime_seconds'])}",
        f"Host:   <code>{html.escape(snapshot['hostname'])}</code>",
        f"DB:     {db}",
        "",
        f"Active users: {_val('active_users')}",
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
        lines.append("<b>Recent jobs (last 3):</b>")
        for j in jobs:
            status = "✅" if j["status"] == "success" else "❌"
            duration = _format_duration_ms(j.get("started_at"),
                                           j.get("finished_at"))
            lines.append(
                f"  {status} <code>{html.escape(j['job_name'])}</code> · {duration}"
            )
    else:
        lines.append("")
        lines.append("<i>No recent job runs recorded.</i>")

    if snapshot.get("errors"):
        lines.append("")
        lines.append(
            "Some fields unavailable: "
            + html.escape("; ".join(snapshot["errors"][:3]))
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
        parse_mode=ParseMode.HTML,
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
                parse_mode=ParseMode.HTML,
                reply_markup=ops_dashboard_keyboard(snapshot["kill_switch_active"]),
            )
        except Exception:  # noqa: BLE001
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


_KS_USAGE = (
    "Usage: <code>/killswitch &lt;pause|resume|lock&gt;</code>\n"
    "  pause  — block all new trades (cached 30s before risk gate sees it)\n"
    "  resume — re-open trade flow (clears lock mode)\n"
    "  lock   — pause + force every user's auto_trade_on=false"
)


async def _broadcast_pause(ctx: ContextTypes.DEFAULT_TYPE | None,
                           message: str,
                           *,
                           pre_fetched_ids: list[int] | None = None) -> int:
    if ctx is None:
        return 0
    if pre_fetched_ids is not None:
        tg_ids = pre_fetched_ids
    else:
        try:
            pool = get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT telegram_user_id FROM users "
                    "WHERE auto_trade_on = TRUE"
                )
            tg_ids = [int(r["telegram_user_id"]) for r in rows
                      if r["telegram_user_id"] is not None]
        except Exception as exc:  # noqa: BLE001
            logger.error("killswitch broadcast user lookup failed: %s", exc)
            return 0

    sent = 0
    for tg_id in tg_ids:
        try:
            await notifications.send(tg_id, message)
            sent += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "killswitch broadcast send failed user=%s err=%s",
                tg_id, exc,
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
    # For lock: capture recipients before set_active() flips auto_trade_on to FALSE.
    lock_recipients: list[int] = []
    if action == "lock":
        try:
            _pool = get_pool()
            async with _pool.acquire() as _conn:
                _rows = await _conn.fetch(
                    "SELECT telegram_user_id FROM users WHERE auto_trade_on = TRUE"
                )
            lock_recipients = [int(r["telegram_user_id"]) for r in _rows
                               if r["telegram_user_id"] is not None]
        except Exception as exc:  # noqa: BLE001
            logger.warning("lock broadcast pre-fetch failed: %s", exc)

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
                "🔴 Kill switch <b>ACTIVE</b>. Auto-trade paused (≤30s "
                "propagation). Use <code>/killswitch resume</code> to re-open.",
                parse_mode=ParseMode.HTML,
            )
        await _broadcast_pause(
            broadcast_via_ctx,
            "🛑 Auto-trade paused by admin. New trades are blocked. "
            "Existing positions remain open until you close them.",
        )
    elif action == "resume":
        if reply is not None:
            await reply("🟢 Kill switch deactivated. Auto-trade resumed.")
    elif action == "lock":
        if reply is not None:
            await reply(
                f"🔒 Kill switch <b>LOCKED</b>. "
                f"{result['users_disabled']} users had auto-trade disabled. "
                "Run <code>/killswitch resume</code> after the incident is addressed; "
                "users must re-opt-in individually.",
                parse_mode=ParseMode.HTML,
            )
        await _broadcast_pause(
            broadcast_via_ctx,
            "🔒 Auto-trade has been locked by admin due to an "
            "incident. Your auto-trade has been turned OFF — re-enable "
            "from /dashboard once confirmed safe.",
            pre_fetched_ids=lock_recipients,
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
        await update.message.reply_text(_KS_USAGE, parse_mode=ParseMode.HTML)
        return
    action = args_list[0].strip().lower()
    if action not in {"pause", "resume", "lock"}:
        await update.message.reply_text(_KS_USAGE, parse_mode=ParseMode.HTML)
        return
    await _apply_killswitch_action(
        action,
        actor_id=update.effective_user.id if update.effective_user else None,
        reply=update.message.reply_text,
        broadcast_via_ctx=ctx,
    )


async def kill_command(update: Update,
                       ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """``/kill`` — operator alias for ``/killswitch pause``."""
    if not _is_operator(update) or update.message is None:
        await _reject_silently(update)
        return
    await _apply_killswitch_action(
        "pause",
        actor_id=update.effective_user.id if update.effective_user else None,
        reply=update.message.reply_text,
        broadcast_via_ctx=ctx,
    )


async def resume_command(update: Update,
                         ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """``/resume`` — operator alias for ``/killswitch resume``."""
    if not _is_operator(update) or update.message is None:
        await _reject_silently(update)
        return
    await _apply_killswitch_action(
        "resume",
        actor_id=update.effective_user.id if update.effective_user else None,
        reply=update.message.reply_text,
        broadcast_via_ctx=ctx,
    )


async def unlock_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """``/unlock @username`` — operator command to release a user account lock."""
    if not _is_operator(update) or update.message is None:
        await _reject_silently(update)
        return
    args = ctx.args or []
    if not args:
        await update.message.reply_text(
            "Usage: <code>/unlock @username</code> or "
            "<code>/unlock &lt;telegram_user_id&gt;</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    target = args[0]
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
        await update.message.reply_text(f"User {target} not found.")
        return
    from ...users import set_locked
    await set_locked(user["id"], False)
    await audit.write(
        actor_role="operator", action="operator_unlock", user_id=user["id"],
    )
    await update.message.reply_text(f"🔓 {target} unlocked.")
    await notifications.send(
        user["telegram_user_id"],
        "🔓 Your account has been unlocked. You can resume trading.",
    )


DEFAULT_JOB_LIMIT = 10
DEFAULT_AUDIT_LIMIT = 20
MAX_OPS_LIMIT = 50


def _parse_limit(args: list[str], default: int) -> tuple[int, bool]:
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
        return ("<i>No matching job runs.</i>" if only_failed
                else "<i>No job runs recorded yet.</i>")
    head = "<b>Recent failed job runs</b>" if only_failed else "<b>Recent job runs</b>"
    lines = [head, ""]
    for r in rows:
        status = "✅" if r["status"] == "success" else "❌"
        ts = r["started_at"].strftime("%m-%d %H:%M:%S") \
            if r.get("started_at") else "—"
        duration = _format_duration_ms(r.get("started_at"), r.get("finished_at"))
        err = _truncate(r.get("error"), 80)
        line = f"{status} <code>{html.escape(r['job_name'])}</code> · {ts} · {duration}"
        if err:
            line += f"\n    └ {html.escape(err)}"
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
        rows = await job_tracker.fetch_recent(limit=limit, only_failed=only_failed)
    except Exception as exc:  # noqa: BLE001
        logger.error("/jobs query failed: %s", exc)
        await update.message.reply_text(f"❌ /jobs query failed: {exc}")
        return
    await update.message.reply_text(
        _render_jobs(rows, only_failed), parse_mode=ParseMode.HTML,
    )


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
        return "<i>Audit log is empty.</i>"
    lines = ["<b>Audit log (most recent first)</b>", ""]
    for r in rows:
        ts = (r["ts"].astimezone(timezone.utc).strftime("%m-%d %H:%M:%S")
              if r.get("ts") else "—")
        user = _truncate(str(r.get("user_id") or ""), 8)
        actor = r.get("actor_role") or "?"
        action = _truncate(r.get("action"), 40)
        lines.append(
            f"<code>{html.escape(ts)}</code> · {html.escape(actor)} · "
            f"{html.escape(action)} · {html.escape(user) or '—'}"
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
        _render_auditlog(rows), parse_mode=ParseMode.HTML,
    )
