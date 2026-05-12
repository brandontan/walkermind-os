"""Telegram handlers for the Copy Trade surface (Phase 5E + 5F).

Entry points
------------
menu_copytrade_handler  Called from the 🐋 Copy Trade reply-keyboard button.
copy_trade_callback     Handles all copytrade: callback queries.
text_input              Handles the paste-address awaiting flow.
copy_trade_command      Legacy /copytrade add/remove/list command.
build_wizard_handler    Returns the Phase 5F ConversationHandler.

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

Phase 5F — Wizard ConversationHandler states
--------------------------------------------
COPY_AMOUNT     Step 1/3: amount mode + preset selection.
COPY_RISK       Step 2/3: risk controls (defaults or edit).
COPY_CONFIRM    Step 3/3: review + start copying.
COPY_EDIT       Per-task edit screen (entered from dashboard Edit button).
COPY_CUSTOM     Awaiting typed custom value for amount/risk/field.

Awaiting keys used
------------------
    copytrade_paste  — user must send a raw wallet address next message.
"""
from __future__ import annotations

import logging
import re
from decimal import Decimal, InvalidOperation
from uuid import UUID

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    CallbackQueryHandler, CommandHandler, ContextTypes,
    ConversationHandler, MessageHandler, filters,
)

from ...database import get_pool
from ...users import upsert_user
from ..keyboards.copy_trade import (
    copy_trade_add_wallet_kb,
    copy_trade_empty_kb,
    copy_trade_task_list_kb,
    discover_filter_kb,
    edit_delete_confirm_kb,
    edit_task_main_kb,
    wallet_stats_kb,
    wizard_amount_mode_kb,
    wizard_custom_cancel_kb,
    wizard_step1_fixed_kb,
    wizard_step1_pct_kb,
    wizard_step2_edit_kb,
    wizard_step2_kb,
    wizard_step3_kb,
    wizard_success_kb,
)
from ..tier import Tier, has_tier, tier_block_message
from ...domain.copy_trade import repository as repo
from ...domain.copy_trade.models import CopyTradeTask
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
        try:
            wallets = await fetch_top_wallets(category or None)
        except Exception as exc:
            logger.warning("copy trade leaderboard fetch failed: %s", exc)
            wallets = []
        if not wallets:
            if q.message:
                await q.message.edit_text(
                    "🐋 *Copy Trade*\n\nWallet data temporarily unavailable.",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Retry", callback_data=f"copytrade:discover:{category}")],
                        [InlineKeyboardButton("↩️ Back", callback_data="copytrade:dashboard")],
                    ]),
                )
            return
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


# ===========================================================================
# Phase 5F — Copy Trade wizard + per-task edit ConversationHandler
# ===========================================================================

# Conversation state tokens
COPY_AMOUNT = 0
COPY_RISK = 1
COPY_CONFIRM = 2
COPY_EDIT = 3
COPY_CUSTOM = 4

_DEFAULTS: dict[str, Decimal] = {
    "tp_pct": Decimal("0.20"),
    "sl_pct": Decimal("0.10"),
    "max_daily_spend": Decimal("100.00"),
    "slippage_pct": Decimal("0.05"),
    "min_trade_size": Decimal("0.50"),
}

_MENU_BUTTONS = {"📊 Dashboard", "🐋 Copy Trade", "🤖 Auto-Trade",
                 "📈 My Trades", "⚙️ Settings", "🛑 Stop Bot"}


# ---------------------------------------------------------------------------
# Wizard data helpers
# ---------------------------------------------------------------------------


def _wz(ctx: ContextTypes.DEFAULT_TYPE) -> dict:
    return ctx.user_data.setdefault("wizard", {})


def _init_wizard(wallet_addr: str) -> dict:
    return {
        "wallet_addr": wallet_addr,
        "copy_mode": "fixed",
        "copy_amount": Decimal("5.00"),
        "copy_pct": None,
        **_DEFAULTS,
        "custom_field": None,
        "custom_context": None,
        "edit_task_id": None,
        "return_state": None,
    }


def _fmt_wz_amount(wz: dict) -> str:
    if wz.get("copy_mode") == "proportional":
        pct = wz.get("copy_pct") or Decimal("0")
        return f"{float(pct) * 100:.0f}% of trader position"
    amt = wz.get("copy_amount") or Decimal("5.00")
    return f"${float(amt):.2f} fixed"


def _step3_text(wz: dict) -> str:
    wallet = _truncate_wallet(wz["wallet_addr"])
    tp = f"+{float(wz['tp_pct']) * 100:.0f}%"
    sl = f"-{float(wz['sl_pct']) * 100:.0f}%"
    maxd = f"${float(wz['max_daily_spend']):.0f}"
    slip = f"{float(wz['slippage_pct']) * 100:.0f}%"
    min_t = f"${float(wz['min_trade_size']):.2f}"
    return (
        "✅ *Confirm Copy Task*\n"
        "━" * 24 + "\n\n"
        f"👛 Wallet: `{wallet}`\n"
        f"💰 Copy: {_fmt_wz_amount(wz)}\n"
        f"📈 Take Profit: {tp}\n"
        f"📉 Stop Loss: {sl}\n"
        f"💳 Max Daily: {maxd}\n"
        f"🔀 Slippage: {slip}\n"
        f"📏 Min Trade: {min_t}\n"
        f"🎲 Mode: Paper\n\n"
        "_Tap Start Copying to activate._"
    )


def _step2_defaults_text(wz: dict) -> str:
    tp = f"+{float(wz['tp_pct']) * 100:.0f}%"
    sl = f"-{float(wz['sl_pct']) * 100:.0f}%"
    maxd = f"${float(wz['max_daily_spend']):.0f}"
    slip = f"{float(wz['slippage_pct']) * 100:.0f}%"
    min_t = f"${float(wz['min_trade_size']):.2f}"
    return (
        "⚙️ *Risk Controls* — Step 2/3\n"
        "━" * 24 + "\n\n"
        f"📈 Take Profit: {tp}\n"
        f"📉 Stop Loss: {sl}\n"
        f"💳 Max Daily Spend: {maxd}\n"
        f"🔀 Slippage: {slip}\n"
        f"📏 Min Trade Size: {min_t}\n\n"
        "Smart defaults pre-applied. Keep or edit."
    )


def _step2_edit_kb_from_wz(wz: dict) -> InlineKeyboardMarkup:
    tp = f"+{float(wz['tp_pct']) * 100:.0f}%"
    sl = f"-{float(wz['sl_pct']) * 100:.0f}%"
    maxd = f"${float(wz['max_daily_spend']):.0f}"
    slip = f"{float(wz['slippage_pct']) * 100:.0f}%"
    min_t = f"${float(wz['min_trade_size']):.2f}"
    return wizard_step2_edit_kb(tp, sl, maxd, slip, min_t)


def _edit_screen_text(task: CopyTradeTask) -> str:
    wallet = _truncate_wallet(task.wallet_address)
    name = task.task_name.replace("_", "\\_").replace("*", "\\*").replace("[", "\\[")
    badge = task.status_badge
    tp = f"+{float(task.tp_pct) * 100:.0f}%"
    sl = f"-{float(task.sl_pct) * 100:.0f}%"
    return (
        f"✏️ *Edit Task — {name}*\n"
        "━" * 24 + "\n\n"
        f"👛 `{wallet}`  {badge} `{task.status}`\n"
        f"💰 Copy: ${float(task.copy_amount):.2f} ({task.copy_mode})\n"
        f"📈 TP: {tp}  📉 SL: {sl}\n\n"
        "_Tap any setting to edit it._"
    )


# ---------------------------------------------------------------------------
# Entry point handlers
# ---------------------------------------------------------------------------


async def wizard_enter_copy(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    """Entry: user tapped '🐋 Copy This Wallet'."""
    q = update.callback_query
    if q is None:
        return ConversationHandler.END
    await q.answer()

    user, ok = await _resolve_user(update)
    if not ok or user is None:
        return ConversationHandler.END

    wallet_addr = (q.data or "")[len("copytrade:copy:"):]
    ctx.user_data["wizard"] = _init_wizard(wallet_addr)

    wallet = _truncate_wallet(wallet_addr)
    text = (
        "🐋 *Copy This Wallet* — Step 1/3\n"
        "━" * 24 + "\n\n"
        f"👛 `{wallet}`\n\n"
        "Choose how to size each copied trade:"
    )
    if q.message:
        await q.message.edit_text(
            text, parse_mode=ParseMode.MARKDOWN,
            reply_markup=wizard_amount_mode_kb(),
        )
    return COPY_AMOUNT


async def wizard_enter_edit(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    """Entry: user tapped 'Edit' on a task card."""
    q = update.callback_query
    if q is None:
        return ConversationHandler.END
    await q.answer()

    user, ok = await _resolve_user(update)
    if not ok or user is None:
        return ConversationHandler.END

    task_id_str = (q.data or "")[len("copytrade:edit:"):]
    try:
        task = await repo.get_task(UUID(task_id_str), user["id"])
    except Exception:
        task = None

    if task is None:
        await q.answer("Task not found.", show_alert=True)
        return ConversationHandler.END

    ctx.user_data["wizard"] = {
        "edit_task_id": task_id_str,
        "custom_field": None,
        "custom_context": "edit",
        "return_state": COPY_EDIT,
    }

    if q.message:
        await q.message.edit_text(
            _edit_screen_text(task),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=edit_task_main_kb(task),
        )
    return COPY_EDIT


# ---------------------------------------------------------------------------
# COPY_AMOUNT state handlers
# ---------------------------------------------------------------------------


async def step1_mode_select(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    """User picked Fixed or % Mirror mode."""
    q = update.callback_query
    if q is None:
        return COPY_AMOUNT
    await q.answer()
    mode = (q.data or "").split(":")[-1]  # "fixed" or "pct"
    wz = _wz(ctx)
    wz["copy_mode"] = "fixed" if mode == "fixed" else "proportional"

    wallet = _truncate_wallet(wz.get("wallet_addr", ""))
    if mode == "fixed":
        text = (
            "💵 *Fixed Amount* — Step 1/3\n"
            "━" * 24 + "\n\n"
            f"👛 `{wallet}`\n\n"
            "Pick the dollar amount to copy per trade:"
        )
        kb = wizard_step1_fixed_kb()
    else:
        text = (
            "📊 *% Mirror* — Step 1/3\n"
            "━" * 24 + "\n\n"
            f"👛 `{wallet}`\n\n"
            "Mirror this % of the trader's position size:"
        )
        kb = wizard_step1_pct_kb()
    if q.message:
        await q.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
    return COPY_AMOUNT


async def step1_fixed_select(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    """User selected a fixed amount preset ($1/$5/$10/$25)."""
    q = update.callback_query
    if q is None:
        return COPY_AMOUNT
    await q.answer()
    amount_str = (q.data or "").split(":")[-1]
    wz = _wz(ctx)
    wz["copy_amount"] = Decimal(amount_str)
    wz["copy_mode"] = "fixed"
    wz["copy_pct"] = None

    if q.message:
        await q.message.edit_text(
            _step2_defaults_text(wz),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=wizard_step2_kb(),
        )
    return COPY_RISK


async def step1_pct_select(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    """User selected a percentage preset (5%/10%/25%/50%)."""
    q = update.callback_query
    if q is None:
        return COPY_AMOUNT
    await q.answer()
    pct_str = (q.data or "").split(":")[-1]
    wz = _wz(ctx)
    wz["copy_pct"] = Decimal(pct_str) / Decimal("100")
    wz["copy_mode"] = "proportional"
    wz["copy_amount"] = Decimal("0")

    if q.message:
        await q.message.edit_text(
            _step2_defaults_text(wz),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=wizard_step2_kb(),
        )
    return COPY_RISK


async def step1_back_to_mode(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    """User tapped ← Mode from fixed/pct grid."""
    q = update.callback_query
    if q is None:
        return COPY_AMOUNT
    await q.answer()
    wz = _wz(ctx)
    wallet = _truncate_wallet(wz.get("wallet_addr", ""))
    if q.message:
        await q.message.edit_text(
            "🐋 *Copy This Wallet* — Step 1/3\n"
            "━" * 24 + "\n\n"
            f"👛 `{wallet}`\n\n"
            "Choose how to size each copied trade:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=wizard_amount_mode_kb(),
        )
    return COPY_AMOUNT


async def step1_custom(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    """User tapped Custom for amount or pct — prompt text input."""
    q = update.callback_query
    if q is None:
        return COPY_AMOUNT
    await q.answer()
    field = (q.data or "").split(":")[-1]  # "amount" or "pct"
    wz = _wz(ctx)
    wz["custom_field"] = field
    wz["custom_context"] = "step1"
    wz["return_state"] = COPY_AMOUNT

    if field == "pct":
        prompt = "Enter percentage (e.g. `15` for 15%):"
        back_data = "wizard:back:mode"
    else:
        prompt = "Enter dollar amount (e.g. `7.50`):"
        back_data = "wizard:back:mode"

    if q.message:
        await q.message.edit_text(
            f"✏️ *Custom {field.title()}*\n━" + "━" * 23 + "\n\n" + prompt,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=wizard_custom_cancel_kb(back_data),
        )
    return COPY_CUSTOM


# ---------------------------------------------------------------------------
# COPY_RISK state handlers
# ---------------------------------------------------------------------------


async def step2_keep(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    """User kept defaults (or tapped Done in edit mode) — go to confirm."""
    q = update.callback_query
    if q is None:
        return COPY_RISK
    await q.answer()
    wz = _wz(ctx)
    if q.message:
        await q.message.edit_text(
            _step3_text(wz),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=wizard_step3_kb(),
        )
    return COPY_CONFIRM


async def step2_edit(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    """User tapped Edit — show risk settings as tappable buttons."""
    q = update.callback_query
    if q is None:
        return COPY_RISK
    await q.answer()
    wz = _wz(ctx)
    if q.message:
        await q.message.edit_text(
            _step2_defaults_text(wz),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=_step2_edit_kb_from_wz(wz),
        )
    return COPY_RISK


async def step2_custom_field(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    """User tapped a risk field button — prompt custom text input."""
    q = update.callback_query
    if q is None:
        return COPY_RISK
    await q.answer()
    field = (q.data or "").split(":")[-1]  # tp / sl / maxd / slip / min
    wz = _wz(ctx)
    wz["custom_field"] = field
    wz["custom_context"] = "step2"
    wz["return_state"] = COPY_RISK

    prompts = {
        "tp":   "Enter take-profit % (e.g. `20` for +20%):",
        "sl":   "Enter stop-loss % (e.g. `10` for -10%):",
        "maxd": "Enter max daily spend in USD (e.g. `150`):",
        "slip": "Enter slippage % (e.g. `5` for 5%):",
        "min":  "Enter minimum trade size in USD (e.g. `1.00`):",
    }
    prompt = prompts.get(field, "Enter value:")
    if q.message:
        await q.message.edit_text(
            f"✏️ *Edit Risk — {field.upper()}*\n━" + "━" * 23 + "\n\n" + prompt,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=wizard_custom_cancel_kb("wizard:back:step2edit"),
        )
    return COPY_CUSTOM


async def step2_back(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    """Back from step 2 to step 1."""
    q = update.callback_query
    if q is None:
        return COPY_AMOUNT
    await q.answer()
    wz = _wz(ctx)
    wallet = _truncate_wallet(wz.get("wallet_addr", ""))
    if q.message:
        await q.message.edit_text(
            "🐋 *Copy This Wallet* — Step 1/3\n"
            "━" * 24 + "\n\n"
            f"👛 `{wallet}`\n\n"
            "Choose how to size each copied trade:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=wizard_amount_mode_kb(),
        )
    return COPY_AMOUNT


# ---------------------------------------------------------------------------
# COPY_CONFIRM state handlers
# ---------------------------------------------------------------------------


async def step3_confirm(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    """User confirmed — create the task row in DB and show success."""
    q = update.callback_query
    if q is None:
        return COPY_CONFIRM
    await q.answer()

    user, ok = await _resolve_user(update)
    if not ok or user is None:
        return ConversationHandler.END

    wz = _wz(ctx)
    wallet_addr = wz["wallet_addr"]
    task_name = f"Copy {_truncate_wallet(wallet_addr)}"

    try:
        task = await repo.create_task(
            user_id=user["id"],
            wallet_address=wallet_addr,
            task_name=task_name,
            copy_mode=wz["copy_mode"],
            copy_amount=wz["copy_amount"],
            copy_pct=wz.get("copy_pct"),
            tp_pct=wz["tp_pct"],
            sl_pct=wz["sl_pct"],
            max_daily_spend=wz["max_daily_spend"],
            slippage_pct=wz["slippage_pct"],
            min_trade_size=wz["min_trade_size"],
        )
    except Exception as exc:
        logger.error("wizard: create_task failed: %s", exc, exc_info=True)
        if q.message:
            await q.message.edit_text(
                "❌ Could not create task. Please try again later.",
                reply_markup=wizard_success_kb(),
            )
        ctx.user_data.pop("wizard", None)
        return ConversationHandler.END

    ctx.user_data.pop("wizard", None)
    if q.message:
        await q.message.edit_text(
            "✅ *Copy task created!*\n"
            "━" * 24 + "\n\n"
            f"👛 `{_truncate_wallet(wallet_addr)}`\n"
            f"💰 {_fmt_wz_amount({**_DEFAULTS, 'copy_mode': task.copy_mode, 'copy_amount': task.copy_amount, 'copy_pct': task.copy_pct})}\n"
            f"🎲 Mode: Paper\n\n"
            "_Task is now active. No real capital deployed._",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=wizard_success_kb(),
        )
    return ConversationHandler.END


async def step3_back(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    """Back from step 3 to step 2."""
    q = update.callback_query
    if q is None:
        return COPY_RISK
    await q.answer()
    wz = _wz(ctx)
    if q.message:
        await q.message.edit_text(
            _step2_defaults_text(wz),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=wizard_step2_kb(),
        )
    return COPY_RISK


# ---------------------------------------------------------------------------
# COPY_EDIT state handlers
# ---------------------------------------------------------------------------


async def edit_field_custom(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    """User tapped an edit field button — prompt custom text input."""
    q = update.callback_query
    if q is None:
        return COPY_EDIT
    await q.answer()
    parts = (q.data or "").split(":")  # wizard:efc:{task_id}:{field}
    if len(parts) < 4:
        return COPY_EDIT
    task_id_str, field = parts[2], parts[3]

    wz = _wz(ctx)
    wz["custom_field"] = field
    wz["custom_context"] = "edit"
    wz["edit_task_id"] = task_id_str
    wz["return_state"] = COPY_EDIT

    prompts = {
        "amount": "Enter copy amount in USD (e.g. `10.00`):",
        "tp":     "Enter take-profit % (e.g. `20` for +20%):",
        "sl":     "Enter stop-loss % (e.g. `10` for -10%):",
        "maxd":   "Enter max daily spend in USD (e.g. `150`):",
        "slip":   "Enter slippage % (e.g. `5` for 5%):",
        "min":    "Enter min trade size in USD (e.g. `1.00`):",
    }
    prompt = prompts.get(field, "Enter value:")
    back_data = f"wizard:eback:edit:{task_id_str}"
    if q.message:
        await q.message.edit_text(
            f"✏️ *Edit — {field.upper()}*\n━" + "━" * 23 + "\n\n" + prompt,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=wizard_custom_cancel_kb(back_data),
        )
    return COPY_CUSTOM


async def edit_field_preset(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    """Handle wizard:ef:{task_id}:rev — toggle reverse_copy."""
    q = update.callback_query
    if q is None:
        return COPY_EDIT
    await q.answer()
    parts = (q.data or "").split(":")  # wizard:ef:{task_id}:rev
    if len(parts) < 4:
        return COPY_EDIT
    task_id_str = parts[2]

    user, ok = await _resolve_user(update)
    if not ok or user is None:
        return COPY_EDIT

    try:
        existing = await repo.get_task(UUID(task_id_str), user["id"])
        if existing is None:
            await q.answer("Task not found.", show_alert=True)
            return COPY_EDIT
        task = await repo.update_task(
            UUID(task_id_str), user["id"],
            reverse_copy=not existing.reverse_copy,
        )
    except Exception as exc:
        logger.error("edit_field_preset failed: %s", exc, exc_info=True)
        return COPY_EDIT

    if task and q.message:
        await q.message.edit_text(
            _edit_screen_text(task),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=edit_task_main_kb(task),
        )
    return COPY_EDIT


async def edit_pause(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    """Toggle task status active ↔ paused."""
    q = update.callback_query
    if q is None:
        return COPY_EDIT
    await q.answer()
    parts = (q.data or "").split(":")  # wizard:epause:{task_id}
    if len(parts) < 3:
        return COPY_EDIT
    task_id_str = parts[2]

    user, ok = await _resolve_user(update)
    if not ok or user is None:
        return COPY_EDIT

    new_status = await repo.toggle_pause(UUID(task_id_str), user["id"])
    if new_status is None:
        await q.answer("Task not found.", show_alert=True)
        return COPY_EDIT

    label = "▶️ resumed" if new_status == "active" else "⏸ paused"
    await q.answer(f"Task {label}")

    try:
        task = await repo.get_task(UUID(task_id_str), user["id"])
    except Exception:
        task = None

    if task and q.message:
        await q.message.edit_text(
            _edit_screen_text(task),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=edit_task_main_kb(task),
        )
    return COPY_EDIT


async def edit_delete_ask(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    """Show delete confirmation dialog."""
    q = update.callback_query
    if q is None:
        return COPY_EDIT
    await q.answer()
    parts = (q.data or "").split(":")  # wizard:edel:ask:{task_id}
    if len(parts) < 4:
        return COPY_EDIT
    task_id_str = parts[3]
    if q.message:
        await q.message.edit_text(
            "🗑 *Delete Task?*\n━" + "━" * 23 + "\n\n"
            "This will permanently remove the copy task.\n"
            "Are you sure?",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=edit_delete_confirm_kb(task_id_str),
        )
    return COPY_EDIT


async def edit_delete_confirm(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    """User confirmed delete — remove task from DB."""
    q = update.callback_query
    if q is None:
        return COPY_EDIT
    await q.answer()
    parts = (q.data or "").split(":")  # wizard:edel:yes:{task_id}
    if len(parts) < 4:
        return COPY_EDIT
    task_id_str = parts[3]

    user, ok = await _resolve_user(update)
    if not ok or user is None:
        return ConversationHandler.END

    try:
        removed = await repo.delete_task(UUID(task_id_str), user["id"])
    except Exception as exc:
        logger.error("edit_delete_confirm failed: %s", exc, exc_info=True)
        removed = False

    ctx.user_data.pop("wizard", None)
    if q.message:
        msg = (
            "🗑 Task deleted." if removed
            else "⚠️ Task not found or already removed."
        )
        await q.message.edit_text(
            msg,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🐋 Copy Trade", callback_data="copytrade:dashboard"),
            ]]),
        )
    return ConversationHandler.END


async def edit_delete_cancel(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    """User cancelled delete — return to edit screen."""
    q = update.callback_query
    if q is None:
        return COPY_EDIT
    await q.answer()
    parts = (q.data or "").split(":")  # wizard:edel:no:{task_id}
    if len(parts) < 4:
        return COPY_EDIT
    task_id_str = parts[3]

    user, ok = await _resolve_user(update)
    if not ok or user is None:
        return ConversationHandler.END

    try:
        task = await repo.get_task(UUID(task_id_str), user["id"])
    except Exception:
        task = None

    if task and q.message:
        await q.message.edit_text(
            _edit_screen_text(task),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=edit_task_main_kb(task),
        )
    return COPY_EDIT


async def edit_pnl(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    """Show per-task P&L summary (stub — execution engine not built yet)."""
    q = update.callback_query
    if q is None:
        return COPY_EDIT
    await q.answer()
    parts = (q.data or "").split(":")  # wizard:epnl:{task_id}
    task_id_str = parts[2] if len(parts) >= 3 else "?"
    if q.message:
        await q.message.reply_text(
            "📊 *Task P&L*\n━" + "━" * 23 + "\n\n"
            "_P&L tracking will be available once the copy execution engine is live._\n\n"
            "🎲 Mode: Paper",
            parse_mode=ParseMode.MARKDOWN,
        )
    return COPY_EDIT


async def edit_rename(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    """Prompt user to type a new task name."""
    q = update.callback_query
    if q is None:
        return COPY_EDIT
    await q.answer()
    parts = (q.data or "").split(":")  # wizard:erename:{task_id}
    if len(parts) < 3:
        return COPY_EDIT
    task_id_str = parts[2]

    wz = _wz(ctx)
    wz["custom_field"] = "task_name"
    wz["custom_context"] = "edit"
    wz["edit_task_id"] = task_id_str
    wz["return_state"] = COPY_EDIT

    if q.message:
        await q.message.edit_text(
            "✏️ *Rename Task*\n━" + "━" * 23 + "\n\n"
            "Type the new name (max 50 chars):",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=wizard_custom_cancel_kb(f"wizard:eback:edit:{task_id_str}"),
        )
    return COPY_CUSTOM


async def edit_back(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    """Back from edit screen to Copy Trade dashboard."""
    q = update.callback_query
    if q is None:
        return ConversationHandler.END
    await q.answer()
    ctx.user_data.pop("wizard", None)
    await menu_copytrade_handler(update, ctx)
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# COPY_CUSTOM state handlers
# ---------------------------------------------------------------------------


async def custom_input_handler(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    """Process typed custom value for amount / risk / edit field."""
    if update.message is None:
        return COPY_CUSTOM

    text = (update.message.text or "").strip()

    # Main menu button tap exits the wizard
    if text in _MENU_BUTTONS:
        ctx.user_data.pop("wizard", None)
        # Let _text_router handle routing
        from ..menus.main import get_menu_route
        handler = get_menu_route(text)
        if handler:
            await handler(update, ctx)
        return ConversationHandler.END

    wz = _wz(ctx)
    field = wz.get("custom_field", "")
    context = wz.get("custom_context", "")

    # Handle task_name (plain string) before numeric parsing so rename works.
    if field == "task_name" and context == "edit":
        task_id_str = wz.get("edit_task_id", "")
        user, ok = await _resolve_user(update)
        if not ok or user is None:
            return ConversationHandler.END
        name = text.strip()[:50]
        if not name:
            await update.message.reply_text(
                "❌ Name cannot be empty. Try again or tap Cancel:",
            )
            return COPY_CUSTOM
        try:
            task = await repo.update_task(UUID(task_id_str), user["id"], task_name=name)
        except Exception as exc:
            logger.error("rename task failed: %s", exc, exc_info=True)
            await update.message.reply_text("❌ Update failed. Please try again.")
            return COPY_CUSTOM
        if task:
            await update.message.reply_text(
                _edit_screen_text(task),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=edit_task_main_kb(task),
            )
        return COPY_EDIT

    # --- parse value ---
    try:
        raw = Decimal(text.replace("$", "").replace("%", "").strip())
    except InvalidOperation:
        await update.message.reply_text(
            "❌ Invalid number. Try again or tap Cancel:",
        )
        return COPY_CUSTOM

    if raw < 0:
        await update.message.reply_text(
            "❌ Value must be positive. Try again:",
        )
        return COPY_CUSTOM

    # --- apply to wizard/task ---
    if context == "step1":
        if field == "amount":
            wz["copy_amount"] = raw
            wz["copy_mode"] = "fixed"
            wz["copy_pct"] = None
        else:  # pct
            if raw > 100:
                await update.message.reply_text("❌ Percentage must be ≤ 100. Try again:")
                return COPY_CUSTOM
            wz["copy_pct"] = raw / Decimal("100")
            wz["copy_mode"] = "proportional"
            wz["copy_amount"] = Decimal("0")
        # Advance to step 2
        await update.message.reply_text(
            _step2_defaults_text(wz),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=wizard_step2_kb(),
        )
        return COPY_RISK

    elif context == "step2":
        _apply_risk_field(wz, field, raw)
        await update.message.reply_text(
            _step2_defaults_text(wz),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=_step2_edit_kb_from_wz(wz),
        )
        return COPY_RISK

    elif context == "edit":
        task_id_str = wz.get("edit_task_id", "")
        user, ok = await _resolve_user(update)
        if not ok or user is None:
            return ConversationHandler.END
        try:
            db_fields = _edit_field_to_db(field, raw, text)
            task = await repo.update_task(UUID(task_id_str), user["id"], **db_fields)
        except Exception as exc:
            logger.error("custom_input edit update failed: %s", exc, exc_info=True)
            await update.message.reply_text("❌ Update failed. Please try again.")
            return COPY_CUSTOM

        if task:
            await update.message.reply_text(
                _edit_screen_text(task),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=edit_task_main_kb(task),
            )
        return COPY_EDIT

    await update.message.reply_text("❌ Unknown context. Try again or tap Cancel.")
    return COPY_CUSTOM


def _apply_risk_field(wz: dict, field: str, raw: Decimal) -> None:
    if field == "tp":
        wz["tp_pct"] = raw / Decimal("100")
    elif field == "sl":
        wz["sl_pct"] = raw / Decimal("100")
    elif field == "maxd":
        wz["max_daily_spend"] = raw
    elif field == "slip":
        wz["slippage_pct"] = raw / Decimal("100")
    elif field == "min":
        wz["min_trade_size"] = raw


def _edit_field_to_db(field: str, raw: Decimal, original_text: str) -> dict:
    if field == "amount":
        return {"copy_amount": raw}
    if field == "tp":
        return {"tp_pct": raw / Decimal("100")}
    if field == "sl":
        return {"sl_pct": raw / Decimal("100")}
    if field == "maxd":
        return {"max_daily_spend": raw}
    if field == "slip":
        return {"slippage_pct": raw / Decimal("100")}
    if field == "min":
        return {"min_trade_size": raw}
    if field == "task_name":
        name = original_text.strip()[:50]
        return {"task_name": name}
    raise ValueError(f"Unknown edit field: {field}")


async def custom_input_back(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    """Cancel button in custom input — return to appropriate state."""
    q = update.callback_query
    if q is None:
        return COPY_CUSTOM
    await q.answer()
    wz = _wz(ctx)
    return_state = wz.get("return_state", COPY_AMOUNT)
    context = wz.get("custom_context", "")

    if context == "edit":
        task_id_str = wz.get("edit_task_id", "")
        user, ok = await _resolve_user(update)
        if not ok or user is None:
            return ConversationHandler.END
        try:
            task = await repo.get_task(UUID(task_id_str), user["id"])
        except Exception:
            task = None
        if task and q.message:
            await q.message.edit_text(
                _edit_screen_text(task),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=edit_task_main_kb(task),
            )
        return COPY_EDIT

    elif return_state == COPY_RISK:
        if q.message:
            await q.message.edit_text(
                _step2_defaults_text(wz),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=wizard_step2_kb(),
            )
        return COPY_RISK

    else:
        wallet = _truncate_wallet(wz.get("wallet_addr", ""))
        if q.message:
            await q.message.edit_text(
                "🐋 *Copy This Wallet* — Step 1/3\n"
                "━" * 24 + "\n\n"
                f"👛 `{wallet}`\n\n"
                "Choose how to size each copied trade:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=wizard_amount_mode_kb(),
            )
        return COPY_AMOUNT


# ---------------------------------------------------------------------------
# Fallback handlers (shared across all states)
# ---------------------------------------------------------------------------


async def wizard_cancel(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    """Cancel wizard and return to Add Wallet screen."""
    q = update.callback_query
    if q is None:
        return ConversationHandler.END
    await q.answer()
    ctx.user_data.pop("wizard", None)
    if q.message:
        await q.message.edit_text(
            "➕ *Add Wallet*\n━" + "━" * 23 + "\n\n"
            "Choose how to add a wallet to copy:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=copy_trade_add_wallet_kb(),
        )
    return ConversationHandler.END


async def wizard_fallback_menu(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    """/menu command in wizard — exit and show menu."""
    ctx.user_data.pop("wizard", None)
    from ..handlers import onboarding
    await onboarding.menu_handler(update, ctx)
    return ConversationHandler.END


async def wizard_menu_tap(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> int:
    """Main menu reply-keyboard tap during wizard — exit and route."""
    if update.message is None:
        return ConversationHandler.END
    text = (update.message.text or "").strip()
    ctx.user_data.pop("wizard", None)
    from ..menus.main import get_menu_route
    handler = get_menu_route(text)
    if handler:
        await handler(update, ctx)
    return ConversationHandler.END


async def wizard_fallback_text(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Unrecognised text while in wizard — show hint, keep current state."""
    if update.message:
        await update.message.reply_text(
            "Couldn't parse that. Tap a button or /menu to exit.",
        )


# ---------------------------------------------------------------------------
# ConversationHandler factory
# ---------------------------------------------------------------------------


def build_wizard_handler() -> ConversationHandler:
    """Return the Phase 5F Copy Trade wizard ConversationHandler."""
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(wizard_enter_copy, pattern=r"^copytrade:copy:"),
            CallbackQueryHandler(wizard_enter_edit, pattern=r"^copytrade:edit:"),
        ],
        states={
            COPY_AMOUNT: [
                CallbackQueryHandler(step1_mode_select,  pattern=r"^wizard:mode:(fixed|pct)$"),
                CallbackQueryHandler(step1_fixed_select, pattern=r"^wizard:fixed:\d+$"),
                CallbackQueryHandler(step1_pct_select,   pattern=r"^wizard:pct:\d+$"),
                CallbackQueryHandler(step1_custom,       pattern=r"^wizard:custom:(amount|pct)$"),
                CallbackQueryHandler(step1_back_to_mode, pattern=r"^wizard:back:mode$"),
                CallbackQueryHandler(wizard_cancel,      pattern=r"^wizard:cancel$"),
            ],
            COPY_RISK: [
                CallbackQueryHandler(step2_keep,         pattern=r"^wizard:keep$"),
                CallbackQueryHandler(step2_edit,         pattern=r"^wizard:risk:edit$"),
                CallbackQueryHandler(step2_custom_field, pattern=r"^wizard:custom:(tp|sl|maxd|slip|min)$"),
                CallbackQueryHandler(step2_back,         pattern=r"^wizard:back:step1$"),
                CallbackQueryHandler(custom_input_back,  pattern=r"^wizard:back:step2edit$"),
                CallbackQueryHandler(wizard_cancel,      pattern=r"^wizard:cancel$"),
            ],
            COPY_CONFIRM: [
                CallbackQueryHandler(step3_confirm, pattern=r"^wizard:confirm$"),
                CallbackQueryHandler(step3_back,    pattern=r"^wizard:back:step2$"),
                CallbackQueryHandler(wizard_cancel, pattern=r"^wizard:cancel$"),
            ],
            COPY_EDIT: [
                CallbackQueryHandler(edit_field_custom,   pattern=r"^wizard:efc:"),
                CallbackQueryHandler(edit_field_preset,   pattern=r"^wizard:ef:"),
                CallbackQueryHandler(edit_pause,          pattern=r"^wizard:epause:"),
                CallbackQueryHandler(edit_delete_ask,     pattern=r"^wizard:edel:ask:"),
                CallbackQueryHandler(edit_delete_confirm, pattern=r"^wizard:edel:yes:"),
                CallbackQueryHandler(edit_delete_cancel,  pattern=r"^wizard:edel:no:"),
                CallbackQueryHandler(edit_pnl,            pattern=r"^wizard:epnl:"),
                CallbackQueryHandler(edit_rename,         pattern=r"^wizard:erename:"),
                CallbackQueryHandler(edit_back,           pattern=r"^wizard:eback$"),
                CallbackQueryHandler(custom_input_back,   pattern=r"^wizard:eback:edit:"),
                CallbackQueryHandler(wizard_cancel,       pattern=r"^wizard:cancel$"),
            ],
            COPY_CUSTOM: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, custom_input_handler,
                ),
                CallbackQueryHandler(custom_input_back, pattern=r"^wizard:(back:|eback:)"),
                CallbackQueryHandler(wizard_cancel,     pattern=r"^wizard:cancel$"),
            ],
        },
        fallbacks=[
            CommandHandler("menu", wizard_fallback_menu),
            MessageHandler(
                filters.Regex(r"^(📊|🐋|🤖|📈|⚙️|🛑)"), wizard_menu_tap,
            ),
            MessageHandler(
                filters.TEXT & ~filters.COMMAND, wizard_fallback_text,
            ),
        ],
        per_message=False,
        allow_reentry=True,
        name="copy_trade_wizard",
    )
