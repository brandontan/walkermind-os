"""Telegram handlers for the /copytrade command surface.

Sub-commands:
    /copytrade add <wallet_address>     — start mirroring a leader wallet
    /copytrade remove <wallet_address>  — stop mirroring a leader wallet
    /copytrade list                     — show the user's active targets

Callback queries:
    copytrade:remove:<wallet_address>   — keyboard "🗑 Stop" handler

Tier gate:
    Tier 2 (ALLOWLISTED) is the floor for every sub-command. The strategy
    plane never executes orders — even at Tier 2 the user is configuring a
    signal source, not committing capital. Capital deployment remains gated
    on Tier 3 (FUNDED) at the execution layer (P3d scope).

Hard cap:
    A user may have at most ``MAX_COPY_TARGETS_PER_USER = 3`` active
    copy_targets rows. The cap is enforced HERE — the DB schema deliberately
    does not carry a cardinality check so the user gets an actionable error
    message instead of a Postgres constraint exception. Inactive ('inactive'
    status) rows do not count toward the cap.
"""
from __future__ import annotations

import logging
import re

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ...database import get_pool
from ...users import upsert_user
from ..keyboards.copy_trade import copy_targets_list_kb
from ..tier import Tier, has_tier, tier_block_message

logger = logging.getLogger(__name__)

MAX_COPY_TARGETS_PER_USER = 3
_WALLET_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _truncate_wallet(addr: str) -> str:
    if len(addr) < 12:
        return addr
    return f"{addr[:8]}…{addr[-4:]}"


def _normalise_wallet(raw: str) -> str | None:
    """Lower-case the address and reject anything not matching 0x + 40 hex.

    Polymarket addresses are checksummed mixed-case on-chain but our DB
    column stores them case-folded so the UNIQUE(user_id, address) cannot
    be tricked by re-casing.
    """
    candidate = raw.strip()
    if not _WALLET_RE.match(candidate):
        return None
    return candidate.lower()


async def _ensure_tier(update: Update, min_tier: int) -> tuple[dict | None, bool]:
    """Resolve the Telegram user, enforce ``min_tier``, route the rejection
    onto whichever surface the update arrived on (message vs. callback).
    """
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


async def _count_active_targets(user_id) -> int:
    pool = get_pool()
    async with pool.acquire() as conn:
        return int(await conn.fetchval(
            "SELECT COUNT(*) FROM copy_targets "
            "WHERE user_id = $1 AND status = 'active'",
            user_id,
        ))


async def _list_active_targets(user_id) -> list[dict]:
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


async def _insert_active_target(user_id, wallet: str) -> str:
    """Insert (or reactivate) a copy target row.

    Returns one of:
        "added"        — a new row was created or a previously inactive
                         row flipped back to 'active'
        "exists"       — the row was already active for this user
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            existing = await conn.fetchrow(
                "SELECT id, status FROM copy_targets "
                "WHERE user_id = $1 AND target_wallet_address = $2",
                user_id, wallet,
            )
            if existing is None:
                await conn.execute(
                    "INSERT INTO copy_targets (user_id, target_wallet_address) "
                    "VALUES ($1, $2)",
                    user_id, wallet,
                )
                return "added"
            if existing["status"] == "active":
                return "exists"
            await conn.execute(
                "UPDATE copy_targets SET status = 'active' "
                "WHERE id = $1",
                existing["id"],
            )
            return "added"


async def _deactivate_target(user_id, wallet: str) -> bool:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE copy_targets SET status = 'inactive' "
            "WHERE user_id = $1 AND target_wallet_address = $2 "
            "  AND status = 'active' "
            "RETURNING id",
            user_id, wallet,
        )
    return row is not None


# ---------------------------------------------------------------------------
# Command entry-point
# ---------------------------------------------------------------------------


_USAGE = (
    "*/copytrade* commands:\n"
    "`/copytrade add <wallet_address>`\n"
    "`/copytrade remove <wallet_address>`\n"
    "`/copytrade list`\n\n"
    f"Max {MAX_COPY_TARGETS_PER_USER} active leaders per account."
)


async def copy_trade_command(update: Update,
                             ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Top-level /copytrade dispatcher.

    Tier 2 gate runs once at the entry-point so every sub-command inherits it.
    """
    if update.message is None:
        return
    user, ok = await _ensure_tier(update, Tier.ALLOWLISTED)
    if not ok or user is None:
        return

    args = ctx.args or []
    if not args:
        await update.message.reply_text(_USAGE, parse_mode=ParseMode.MARKDOWN)
        return

    sub = args[0].lower()
    if sub == "add":
        await _handle_add(update, user["id"], args[1:])
        return
    if sub == "remove":
        await _handle_remove(update, user["id"], args[1:])
        return
    if sub == "list":
        await _handle_list(update, user["id"])
        return
    await update.message.reply_text(_USAGE, parse_mode=ParseMode.MARKDOWN)


# ---------------------------------------------------------------------------
# Sub-command handlers
# ---------------------------------------------------------------------------


async def _handle_add(update: Update, user_id, args: list[str]) -> None:
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

    active_count = await _count_active_targets(user_id)
    if active_count >= MAX_COPY_TARGETS_PER_USER:
        await update.message.reply_text(
            f"❌ You already have {MAX_COPY_TARGETS_PER_USER} active copy "
            "targets. Remove one before adding another.",
        )
        return

    result = await _insert_active_target(user_id, wallet)
    if result == "exists":
        await update.message.reply_text(
            f"Already copying `{_truncate_wallet(wallet)}`.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    await update.message.reply_text(
        f"✅ Now copying `{_truncate_wallet(wallet)}`.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def _handle_remove(update: Update, user_id, args: list[str]) -> None:
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

    removed = await _deactivate_target(user_id, wallet)
    if not removed:
        await update.message.reply_text(
            f"No active copy target matching `{_truncate_wallet(wallet)}`.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    await update.message.reply_text(
        f"🛑 Stopped copying `{_truncate_wallet(wallet)}`.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def _handle_list(update: Update, user_id) -> None:
    if update.message is None:
        return
    targets = await _list_active_targets(user_id)
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
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=copy_targets_list_kb(
            [t["target_wallet_address"] for t in targets],
        ),
    )


# ---------------------------------------------------------------------------
# Callback (keyboard) — copytrade:remove:<wallet>
# ---------------------------------------------------------------------------


async def copy_trade_callback(update: Update,
                              ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the [🗑 Stop] inline-keyboard button on the list view."""
    q = update.callback_query
    if q is None:
        return
    user, ok = await _ensure_tier(update, Tier.ALLOWLISTED)
    if not ok or user is None:
        return
    await q.answer()

    data = q.data or ""
    parts = data.split(":", 2)
    if len(parts) != 3 or parts[1] != "remove":
        return
    wallet = _normalise_wallet(parts[2])
    if wallet is None:
        return
    removed = await _deactivate_target(user["id"], wallet)
    if removed:
        await q.message.reply_text(
            f"🛑 Stopped copying `{_truncate_wallet(wallet)}`.",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await q.message.reply_text(
            f"No active copy target matching `{_truncate_wallet(wallet)}`.",
            parse_mode=ParseMode.MARKDOWN,
        )
