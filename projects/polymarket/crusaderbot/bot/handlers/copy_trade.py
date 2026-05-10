"""Telegram handlers for the Copy Trade surface (Phase 5E).

Entry points
------------
menu_copytrade_handler  Called from the 🐋 Copy Trade reply-keyboard button.
copy_trade_callback     Handles all copytrade: callback queries.
text_input              Handles the paste-address awaiting flow.
copy_trade_command      Legacy /copytrade add/remove/list command.

Dashboard states
----------------
Empty  : no copy_trade_tasks rows for this user.
        Shows empty-state message + [Add Wallet] [Discover] buttons.
Filled : one or more copy_trade_tasks rows.
        Shows per-task cards with [Pause/Resume] [Edit] and total PnL row.

Add Wallet paths
----------------
Path A — Paste Address : user sends a wallet address; bot sets
    ctx.user_data['awaiting'] = 'copytrade_paste', then text_input
    fetches stats and shows the wallet stats card.
Path B — Smart Discovery : leaderboard of top 10 wallets by 30d PnL
    from Polymarket Gamma API with 6 filter categories.

Scope boundary (Phase 5E)
-------------------------
- Copy task setup wizard is Phase 5F scope (copytrade:copy:* → placeholder).
- Per-task edit wizard is Phase 5F scope (copytrade:edit:* → placeholder).
- No execution logic is built here.

Awaiting keys used
------------------
    copytrade_paste  — user must send a raw wallet address next message.
"""
from __future__ import annotations

import logging
import re
from uuid import UUID

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ...database import get_pool
from ...users import upsert_user
from ..keyboards.copy_trade import (
    copy_trade_add_wallet_kb,
    copy_trade_empty_kb,
    copy_trade_task_list_kb,
    discover_filter_kb,
    wallet_stats_kb,
)
from ..tier import Tier, has_tier, tier_block_message
from ...services.copy_trade.wallet_stats import (
    WalletStats,
    fetch_top_wallets,
    fetch_wallet_stats,
)

logger = logging.getLogger(__name__)

_WALLET_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")

# Legacy constant (copy_targets table cap — unchanged from P3 implementation)
MAX_COPY_TARGETS_PER_USER = 3


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _truncate_wallet(addr: str) -> str:
    if len(addr) < 12:
        return addr
    return f"{addr[:8]}…{addr[-4:]}"


def _normalise_wallet(raw: str) -> str | None:
    candidate = raw.strip()
    if not _WALLET_RE.match(candidate):
        return None
    return candidate.lower()


async def _resolve_user(update: Update, min_tier: int = Tier.ALLOWLISTED):
    """Upsert user and check tier. Returns (user, ok) tuple."""
    if update.effective_user is None:
        return None, False
    user = await upsert_user(
        update.effective_user.id, update.effective_user.username,
    )
    if not has_tier(user["access_tier"], min_tier):
        msg = tier_block_message(min_tier)
        if update.callback_query is not None:
            await update.callback_query.answer(msg, show_alert=True)
        elif update.message is not None:
            await update.message.reply_text(msg)
        return None, False
    return user, True


async def _list_copy_tasks(user_id: UUID) -> list[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id::text, wallet_address, task_name, status,
                   copy_amount, copy_mode
              FROM copy_trade_tasks
             WHERE user_id = $1
             ORDER BY created_at ASC
            """,
            user_id,
        )
    return [dict(r) for r in rows]


async def _toggle_task_pause(task_id: str, user_id: UUID) -> str | None:
    """Flip status between 'active' and 'paused'. Returns new status or None."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status FROM copy_trade_tasks WHERE id = $1 AND user_id = $2",
            UUID(task_id), user_id,
        )
        if row is None:
            return None
        new_status = "active" if row["status"] == "paused" else "paused"
        await conn.execute(
            "UPDATE copy_trade_tasks SET status = $1, updated_at = NOW() "
            "WHERE id = $2 AND user_id = $3",
            new_status, UUID(task_id), user_id,
        )
    return new_status


# ---------------------------------------------------------------------------
# Text formatters
# ---------------------------------------------------------------------------


def _fmt_pnl(v: float | None) -> str:
    if v is None:
        return "—"
    sign = "+" if v >= 0 else ""
    return f"${sign}{v:,.2f}"


def _fmt_pct(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v * 100:.1f}%"


def _fmt_usd(v: float | None) -> str:
    if v is None:
        return "—"
    return f"${v:,.2f}"


def _dashboard_text(tasks: list[dict]) -> str:
    if not tasks:
        return (
            "🐋 *Copy Trade*\n"
            "━━━━━━━━━━"
            "━━━━━━━━━━━━━━\n\n"
            "_No wallets followed yet._\n\n"
            "Add a wallet to start mirroring trades automatically."
        )

    lines = [
        "🐋 *Copy Trade*",
        "━" * 24,
        "",
    ]
    for i, t in enumerate(tasks, 1):
        badge = {"active": "🟢", "paused": "⏸", "stopped": "🔴"}.get(t["status"], "❓")
        # Escape Markdown special chars in user-supplied task name to prevent
        # Telegram parse-entities error when name contains _, *, [, etc.
        name = t["task_name"].replace("_", "\\_").replace("*", "\\*").replace("[", "\\[")
        wallet = _truncate_wallet(t["wallet_address"])
        amount = f"${float(t['copy_amount']):,.2f} ({t['copy_mode']})"
        lines += [
            f"*{i}. {name}*  {badge} `{t['status']}`",
            f"   👛 `{wallet}`",
            f"   💰 Copy: {amount}",
            f"   📊 Your PnL: —   🏦 Trader 30d: —",
            f"   📌 Active positions: —",
            "",
        ]
    lines.append("📊 *Total Copy PnL: —*")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main entry point — 🐋 Copy Trade menu button
# ---------------------------------------------------------------------------


async def menu_copytrade_handler(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Phase 5E: Copy Trade dashboard entry point (replaces 5D placeholder)."""
    user, ok = await _resolve_user(update)
    if not ok or user is None:
        return

    tasks = await _list_copy_tasks(user["id"])
    text = _dashboard_text(tasks)

    kb: InlineKeyboardMarkup
    if tasks:
        kb = copy_trade_task_list_kb(
            [t["id"] for t in tasks],
            [t["status"] for t in tasks],
        )
    else:
        kb = copy_trade_empty_kb()

    if update.message is not None:
        await update.message.reply_text(
            text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb,
        )
    elif update.callback_query is not None:
        await update.callback_query.answer()
        if update.callback_query.message is not None:
            await update.callback_query.message.edit_text(
                text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb,
            )


# ---------------------------------------------------------------------------
# Callback dispatcher — all copytrade: patterns
# ---------------------------------------------------------------------------


async def copy_trade_callback(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Route all copytrade: callback queries."""
    q = update.callback_query
    if q is None:
        return
    user, ok = await _resolve_user(update)
    if not ok or user is None:
        return

    data: str = q.data or ""
    # Strip prefix
    action = data[len("copytrade:"):]

    # -- dashboard --
    if action == "dashboard":
        await q.answer()
        if ctx.user_data:
            ctx.user_data.pop("awaiting", None)
        await menu_copytrade_handler(update, ctx)
        return

    # -- add wallet screen --
    if action == "add":
        await q.answer()
        if ctx.user_data:
            ctx.user_data.pop("awaiting", None)
        if q.message:
            await q.message.edit_text(
                "➕ *Add Wallet*\n━" * 1 + "━" * 23 + "\n\n"
                "Choose how to add a wallet to copy:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=copy_trade_add_wallet_kb(),
            )
        return

    # -- paste address: set awaiting and prompt --
    if action == "paste":
        await q.answer()
        if ctx.user_data is not None:
            ctx.user_data["awaiting"] = "copytrade_paste"
        if q.message:
            await q.message.edit_text(
                "📋 *Paste Wallet Address*\n━" + "━" * 23 + "\n\n"
                "Send the wallet address you want to follow.\n"
                "Format: `0x` + 40 hex characters",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("✕ Cancel", callback_data="copytrade:add"),
                ]]),
            )
        return

    # -- smart discovery leaderboard --
    if action == "discover" or action.startswith("discover:"):
        await q.answer()
        category = action[len("discover:"):] if ":" in action else "top_pnl"
        wallets = await fetch_top_wallets(category or None)
        text = _leaderboard_text(wallets, category)
        if q.message:
            await q.message.edit_text(
                text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=discover_filter_kb(category),
            )
        return

    # -- single wallet stats card (from paste flow callback) --
    if action.startswith("stats:"):
        await q.answer()
        address = action[len("stats:"):]
        stats = await fetch_wallet_stats(address)
        if q.message:
            await q.message.edit_text(
                _wallet_stats_text(stats),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=wallet_stats_kb(address),
            )
        return

    # -- copy this wallet (Phase 5F wizard placeholder) --
    if action.startswith("copy:"):
        await q.answer(
            "Setup wizard coming in Phase 5F. Stay tuned! 🚀", show_alert=True,
        )
        return

    # -- pause / resume task --
    if action.startswith("pause:"):
        task_id = action[len("pause:"):]
        new_status = await _toggle_task_pause(task_id, user["id"])
        if new_status is None:
            await q.answer("Task not found.", show_alert=True)
            return
        label = "resumed ▶️" if new_status == "active" else "paused ⏸"
        await q.answer(f"Task {label}")
        # Re-render dashboard
        await menu_copytrade_handler(update, ctx)
        return

    # -- edit task (Phase 5F wizard placeholder) --
    if action.startswith("edit:"):
        await q.answer(
            "Edit wizard coming in Phase 5F. Stay tuned! 🚀", show_alert=True,
        )
        return

    # -- legacy: remove from copy_targets --
    if action.startswith("remove:"):
        wallet = _normalise_wallet(action[len("remove:"):])
        if wallet is None:
            await q.answer()
            return
        removed = await _legacy_deactivate_target(user["id"], wallet)
        await q.answer()
        reply = (
            f"🛑 Stopped copying `{_truncate_wallet(wallet)}`."
            if removed
            else f"No active copy target matching `{_truncate_wallet(wallet)}`."
        )
        if q.message:
            await q.message.reply_text(reply, parse_mode=ParseMode.MARKDOWN)
        return

    await q.answer()


# ---------------------------------------------------------------------------
# Text input — paste address awaiting flow
# ---------------------------------------------------------------------------


async def text_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle paste-address input. Returns True if the message was consumed."""
    awaiting = (ctx.user_data or {}).get("awaiting")
    if awaiting != "copytrade_paste":
        return False

    if update.message is None:
        return True

    raw = (update.message.text or "").strip()
    wallet = _normalise_wallet(raw)
    if wallet is None:
        await update.message.reply_text(
            "❌ Invalid address. Expected `0x` + 40 hex characters. Try again:",
            parse_mode=ParseMode.MARKDOWN,
        )
        return True  # consumed but awaiting stays set

    if ctx.user_data is not None:
        ctx.user_data.pop("awaiting", None)

    stats = await fetch_wallet_stats(wallet)
    await update.message.reply_text(
        _wallet_stats_text(stats),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=wallet_stats_kb(wallet),
    )
    return True


# ---------------------------------------------------------------------------
# Legacy /copytrade command (copy_targets table — unchanged from P3)
# ---------------------------------------------------------------------------


_USAGE = (
    "*/copytrade* commands:\n"
    "`/copytrade add <wallet_address>`\n"
    "`/copytrade remove <wallet_address>`\n"
    "`/copytrade list`\n\n"
    f"Max {MAX_COPY_TARGETS_PER_USER} active leaders per account."
)


async def copy_trade_command(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Legacy /copytrade command dispatcher (copy_targets table)."""
    if update.message is None:
        return
    user, ok = await _resolve_user(update)
    if not ok or user is None:
        return
    args = ctx.args or []
    if not args:
        await update.message.reply_text(_USAGE, parse_mode=ParseMode.MARKDOWN)
        return
    sub = args[0].lower()
    if sub == "add":
        await _legacy_add(update, user["id"], args[1:])
    elif sub == "remove":
        await _legacy_remove(update, user["id"], args[1:])
    elif sub == "list":
        await _legacy_list(update, user["id"])
    else:
        await update.message.reply_text(_USAGE, parse_mode=ParseMode.MARKDOWN)


# ---------------------------------------------------------------------------
# Legacy helpers — copy_targets table
# ---------------------------------------------------------------------------


async def _legacy_list_active(user_id: UUID) -> list[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT target_wallet_address, trades_mirrored, created_at
              FROM copy_targets
             WHERE user_id = $1 AND status = 'active'
             ORDER BY created_at ASC
            """,
            user_id,
        )
    return [dict(r) for r in rows]


async def _insert_active_target(user_id: UUID, wallet: str) -> str:
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext($1))", str(user_id),
            )
            existing = await conn.fetchrow(
                "SELECT id, status FROM copy_targets "
                "WHERE user_id = $1 AND target_wallet_address = $2",
                user_id, wallet,
            )
            if existing is not None and existing["status"] == "active":
                return "exists"
            count = int(await conn.fetchval(
                "SELECT COUNT(*) FROM copy_targets "
                "WHERE user_id = $1 AND status = 'active'", user_id,
            ))
            if count >= MAX_COPY_TARGETS_PER_USER:
                return "cap_exceeded"
            if existing is None:
                await conn.execute(
                    "INSERT INTO copy_targets (user_id, target_wallet_address) "
                    "VALUES ($1, $2)", user_id, wallet,
                )
            else:
                await conn.execute(
                    "UPDATE copy_targets SET status = 'active' WHERE id = $1",
                    existing["id"],
                )
    return "added"


async def _legacy_deactivate_target(user_id: UUID, wallet: str) -> bool:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE copy_targets SET status = 'inactive' "
            "WHERE user_id = $1 AND target_wallet_address = $2 AND status = 'active' "
            "RETURNING id",
            user_id, wallet,
        )
    return row is not None


async def _legacy_add(
    update: Update, user_id: UUID, args: list[str],
) -> None:
    if update.message is None:
        return
    if len(args) != 1:
        await update.message.reply_text(
            "Usage: `/copytrade add <wallet_address>`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    wallet = _normalise_wallet(args[0])
    if wallet is None:
        await update.message.reply_text(
            "❌ Invalid wallet address. Expected `0x` + 40 hex chars.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    result = await _insert_active_target(user_id, wallet)
    if result == "cap_exceeded":
        await update.message.reply_text(
            f"❌ You already have {MAX_COPY_TARGETS_PER_USER} active copy "
            "targets. Remove one before adding another.",
        )
    elif result == "exists":
        await update.message.reply_text(
            f"Already copying `{_truncate_wallet(wallet)}`.",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text(
            f"✅ Now copying `{_truncate_wallet(wallet)}`.",
            parse_mode=ParseMode.MARKDOWN,
        )


async def _legacy_remove(
    update: Update, user_id: UUID, args: list[str],
) -> None:
    if update.message is None:
        return
    if len(args) != 1:
        await update.message.reply_text(
            "Usage: `/copytrade remove <wallet_address>`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    wallet = _normalise_wallet(args[0])
    if wallet is None:
        await update.message.reply_text(
            "❌ Invalid wallet address. Expected `0x` + 40 hex chars.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    removed = await _legacy_deactivate_target(user_id, wallet)
    if removed:
        await update.message.reply_text(
            f"🛑 Stopped copying `{_truncate_wallet(wallet)}`.",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text(
            f"No active copy target matching `{_truncate_wallet(wallet)}`.",
            parse_mode=ParseMode.MARKDOWN,
        )


async def _legacy_list(update: Update, user_id: UUID) -> None:
    if update.message is None:
        return
    from ..keyboards.copy_trade import copy_trade_empty_kb as _empty_kb
    targets = await _legacy_list_active(user_id)
    if not targets:
        await update.message.reply_text(
            "No active copy targets. Add one with "
            "`/copytrade add <wallet_address>`.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    lines = ["*Active copy targets*\n"]
    for t in targets:
        wallet = t["target_wallet_address"]
        added = t["created_at"].strftime("%Y-%m-%d")
        lines.append(
            f"`{_truncate_wallet(wallet)}` · added {added} · "
            f"mirrored {t['trades_mirrored']}"
        )
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    rows = [[InlineKeyboardButton(
        f"🗑 Stop {_truncate_wallet(t['target_wallet_address'])}",
        callback_data=f"copytrade:remove:{t['target_wallet_address']}",
    )] for t in targets]
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(rows),
    )


def _wallet_stats_text(stats: WalletStats) -> str:
    wallet = _truncate_wallet(stats.address)
    header = (
        "📊 *Wallet Stats*\n"
        "━" * 24 + "\n"
        f"`{wallet}`\n"
    )
    if not stats.available:
        return (
            header
            + "\n⚠️ _Stats unavailable — API error_\n\n"
            "_You can still set up copy trading for this wallet._"
        )
    return (
        header
        + f"\n💰 30d PnL: {_fmt_pnl(stats.pnl_30d)}"
        + f"\n🎯 Win Rate: {_fmt_pct(stats.win_rate)}"
        + f"\n📈 Avg Trade: {_fmt_usd(stats.avg_trade)}"
        + f"\n📊 Trades: {stats.trades_count}"
        + f"\n🏦 Active Positions: {stats.active_positions}"
        + f"\n🏷 Category: {stats.category}"
        + "\n\n_Stats from Polymarket · refreshed every 5 min_"
    )


def _leaderboard_text(wallets: list[WalletStats], active_filter: str) -> str:
    label_map = {
        "crypto": "Crypto", "sports": "Sports", "politics": "Politics",
        "world": "World", "top_pnl": "Top PnL", "top_wr": "Top Win Rate",
    }
    filter_label = label_map.get(active_filter, "Top PnL")
    if not wallets:
        return (
            f"🔍 *Top Wallets — {filter_label}*\n"
            "━" * 24 + "\n\n"
            "⚠️ _Leaderboard unavailable. Try again shortly._"
        )
    lines = [
        f"🔍 *Top Wallets — {filter_label}*",
        "━" * 24,
        "",
    ]
    for i, w in enumerate(wallets, 1):
        wallet = _truncate_wallet(w.address)
        lines += [
            f"*#{i}*  `{wallet}`",
            f"   💰 {_fmt_pnl(w.pnl_30d)}  🎯 WR: {_fmt_pct(w.win_rate)}",
            f"   📊 Trades: {w.trades_count}  🏷 {w.category}",
            f"   🎯 Match: 0%",
            "",
        ]
    return "\n".join(lines)
