"""Telegram handlers for the /signals command surface (P3c).

Sub-commands:
    /signals                       - usage hint + active subscription count
    /signals list                  - show the user's active subscriptions
    /signals catalog               - show feeds available to subscribe to
    /signals on <feed_slug>        - subscribe to a feed
    /signals off <feed_slug>       - unsubscribe from a feed

Callback queries:
    signals:off:<feed_slug>        - keyboard "\U0001F6D1 Off" handler

Tier gate:
    Tier 2 (ALLOWLISTED) is the floor for every sub-command. The strategy
    plane never executes orders — even at Tier 2 the user is configuring a
    signal source, not committing capital. Capital deployment remains gated
    on Tier 3 (FUNDED) at the execution layer (P3d scope).

Hard cap:
    A user may have at most ``MAX_SUBSCRIPTIONS_PER_USER = 5`` active
    user_signal_subscriptions rows. The cap is enforced inside
    ``services.signal_feed.subscribe`` under a pg_advisory_xact_lock so two
    concurrent /signals on calls cannot race past the cap. The handler
    surfaces the result code as an actionable message to the user.
"""
from __future__ import annotations

import logging
import re

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ...services.signal_feed import (
    MAX_SUBSCRIPTIONS_PER_USER,
    get_feed_by_slug,
    list_active_feeds,
    list_user_subscriptions,
    subscribe,
    unsubscribe,
)
from ...users import upsert_user
from ..keyboards.signal_following import signal_subs_list_kb
from ..tier import Tier, has_tier, tier_block_message

logger = logging.getLogger(__name__)

# Max slug length is capped at 50 chars so the inline-keyboard
# callback_data ("signals:off:<slug>" — 12-byte prefix) stays within
# Telegram's 64-byte ceiling. Service-side create_feed enforces the same
# bound so the contract holds end-to-end.
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,49}$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalise_slug(raw: str) -> str | None:
    """Lower-case the slug and reject anything not matching the slug regex."""
    candidate = (raw or "").strip().lower()
    if not _SLUG_RE.match(candidate):
        return None
    return candidate


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


# ---------------------------------------------------------------------------
# Command entry-point
# ---------------------------------------------------------------------------


_USAGE = (
    "*/signals* commands:\n"
    "`/signals list`\n"
    "`/signals catalog`\n"
    "`/signals on <feed_slug>`\n"
    "`/signals off <feed_slug>`\n\n"
    f"Max {MAX_SUBSCRIPTIONS_PER_USER} active subscriptions per account."
)


async def signals_command(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Top-level /signals dispatcher.

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
    if sub == "list":
        await _handle_list(update, user["id"])
        return
    if sub == "catalog":
        await _handle_catalog(update)
        return
    if sub == "on":
        await _handle_on(update, user["id"], args[1:])
        return
    if sub == "off":
        await _handle_off(update, user["id"], args[1:])
        return
    await update.message.reply_text(_USAGE, parse_mode=ParseMode.MARKDOWN)


# ---------------------------------------------------------------------------
# Sub-command handlers
# ---------------------------------------------------------------------------


async def _handle_list(update: Update, user_id) -> None:
    if update.message is None:
        return
    subs = await list_user_subscriptions(user_id)
    if not subs:
        await update.message.reply_text(
            "No active signal subscriptions. Browse with "
            "`/signals catalog` and subscribe via "
            "`/signals on <feed_slug>`.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    lines = ["*Active signal subscriptions*\n"]
    for s in subs:
        slug = s["feed_slug"]
        name = s["feed_name"]
        added = s["subscribed_at"].strftime("%Y-%m-%d")
        lines.append(f"`{slug}` · {name} · added {added}")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=signal_subs_list_kb(
            [(s["feed_slug"], s["feed_name"]) for s in subs],
        ),
    )


async def _handle_catalog(update: Update) -> None:
    if update.message is None:
        return
    feeds = await list_active_feeds()
    if not feeds:
        await update.message.reply_text(
            "No active signal feeds available right now.",
        )
        return
    lines = ["*Available signal feeds*\n"]
    for f in feeds:
        desc = f.get("description") or ""
        suffix = f" — {desc}" if desc else ""
        lines.append(
            f"`{f['slug']}` · {f['name']} · "
            f"{f['subscriber_count']} subs{suffix}"
        )
    lines.append("\nSubscribe with `/signals on <feed_slug>`.")
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
    )


async def _handle_on(update: Update, user_id, args: list[str]) -> None:
    if update.message is None:
        return
    if len(args) != 1:
        await update.message.reply_text(
            "Usage: `/signals on <feed_slug>`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    slug = _normalise_slug(args[0])
    if slug is None:
        await update.message.reply_text(
            "❌ Invalid feed slug. Use lowercase letters, digits, "
            "`_`, or `-`.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    feed = await get_feed_by_slug(slug)
    if feed is None:
        await update.message.reply_text(
            f"❌ No feed `{slug}`. Run `/signals catalog`.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    result = await subscribe(user_id=user_id, feed_id=feed["id"])
    if result == "cap_exceeded":
        await update.message.reply_text(
            f"❌ You already have {MAX_SUBSCRIPTIONS_PER_USER} active "
            "signal subscriptions. Turn one off before adding another.",
        )
        return
    if result == "exists":
        await update.message.reply_text(
            f"Already subscribed to `{slug}`.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    if result == "feed_inactive":
        await update.message.reply_text(
            f"Feed `{slug}` is not currently active.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    if result == "unknown_feed":
        await update.message.reply_text(
            f"❌ No feed `{slug}`. Run `/signals catalog`.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    await update.message.reply_text(
        f"✅ Subscribed to `{slug}`.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def _handle_off(update: Update, user_id, args: list[str]) -> None:
    if update.message is None:
        return
    if len(args) != 1:
        await update.message.reply_text(
            "Usage: `/signals off <feed_slug>`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    slug = _normalise_slug(args[0])
    if slug is None:
        await update.message.reply_text(
            "❌ Invalid feed slug.",
        )
        return
    feed = await get_feed_by_slug(slug)
    if feed is None:
        await update.message.reply_text(
            f"No feed `{slug}`.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    flipped = await unsubscribe(user_id=user_id, feed_id=feed["id"])
    if not flipped:
        await update.message.reply_text(
            f"No active subscription to `{slug}`.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    await update.message.reply_text(
        f"\U0001F6D1 Unsubscribed from `{slug}`.",
        parse_mode=ParseMode.MARKDOWN,
    )


# ---------------------------------------------------------------------------
# Callback (keyboard) - signals:off:<feed_slug>
# ---------------------------------------------------------------------------


async def signals_callback(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Handle the [\U0001F6D1 Off] inline-keyboard button on the list view."""
    q = update.callback_query
    if q is None:
        return
    user, ok = await _ensure_tier(update, Tier.ALLOWLISTED)
    if not ok or user is None:
        return
    await q.answer()

    data = q.data or ""
    parts = data.split(":", 2)
    if len(parts) != 3 or parts[1] != "off":
        return
    slug = _normalise_slug(parts[2])
    if slug is None:
        return
    feed = await get_feed_by_slug(slug)
    if feed is None:
        await q.message.reply_text(
            f"No feed `{slug}`.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    flipped = await unsubscribe(user_id=user["id"], feed_id=feed["id"])
    if flipped:
        await q.message.reply_text(
            f"\U0001F6D1 Unsubscribed from `{slug}`.",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await q.message.reply_text(
            f"No active subscription to `{slug}`.",
            parse_mode=ParseMode.MARKDOWN,
        )
