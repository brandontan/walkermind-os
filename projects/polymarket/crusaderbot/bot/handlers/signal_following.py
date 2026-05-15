"""Telegram handlers for the /signals command surface (P3c).

Sub-commands:
    /signals                       - usage hint + active subscription count
    /signals list                  - show the user's active subscriptions
    /signals catalog               - show feeds available to subscribe to
    /signals on <feed_slug>        - subscribe to a feed
    /signals off <feed_slug>       - unsubscribe from a feed

Callback queries:
    signals:off:<feed_slug>        - keyboard "\U0001F6D1 Off" handler

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

from telegram import InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ...services.signal_feed import (
    MAX_SUBSCRIPTIONS_PER_USER,
    SLUG_PATTERN,
    get_feed_by_slug,
    list_active_feeds,
    list_user_subscriptions,
    subscribe,
    unsubscribe,
)
from ...users import upsert_user
from ..keyboards.signal_following import signal_subs_list_kb


logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(SLUG_PATTERN)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalise_slug(raw: str) -> str | None:
    """Lower-case the slug and reject anything not matching the slug regex."""
    candidate = (raw or "").strip().lower()
    if not _SLUG_RE.match(candidate):
        return None
    return candidate


_MARKDOWN_METACHARS = ("_", "*", "`", "[")


def _escape_md(text: str | None) -> str:
    """Escape Telegram Markdown V1 metacharacters in operator-supplied text."""
    if not text:
        return ""
    out = text.replace("\\", "\\\\")
    for ch in _MARKDOWN_METACHARS:
        out = out.replace(ch, "\\" + ch)
    return out


async def _ensure_user(update: Update) -> tuple[dict | None, bool]:
    if update.effective_user is None:
        return None, False
    user = await upsert_user(
        update.effective_user.id, update.effective_user.username,
    )
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


async def _build_signals_screen(user_id) -> tuple[str, InlineKeyboardMarkup]:
    """Build the signal feed hub text and keyboard (hierarchy tree style)."""
    from telegram import InlineKeyboardButton
    from ..keyboards import nav_row

    subs = await list_user_subscriptions(user_id)
    all_feeds = await list_active_feeds()
    subbed_slugs = {s["feed_slug"] for s in subs}

    if subs:
        sub_tree_lines = []
        for i, s in enumerate(subs):
            connector = "└" if i == len(subs) - 1 else "├"
            sub_tree_lines.append(f"{connector} ✅ {_escape_md(s['feed_name'])}")
        sub_tree = "\n".join(sub_tree_lines)
    else:
        sub_tree = "└ None yet"

    avail = [f for f in all_feeds if f["slug"] not in subbed_slugs]
    if avail:
        avail_tree_lines = []
        for i, f in enumerate(avail):
            connector = "└" if i == len(avail) - 1 else "├"
            avail_tree_lines.append(f"{connector} {_escape_md(f['name'])}")
        avail_tree = "\n".join(avail_tree_lines)
    else:
        avail_tree = "└ None available"

    text = (
        "📡 Signal Feeds\n"
        "\n"
        "Status\n"
        f"└ {len(subs)} Following\n"
        "\n"
        "Following\n"
        f"{sub_tree}\n"
        "\n"
        "Available\n"
        f"{avail_tree}\n"
        "\n"
        f"Max {MAX_SUBSCRIPTIONS_PER_USER} active"
    )

    buttons: list[list[InlineKeyboardButton]] = []
    for f in all_feeds:
        subscribed = f["slug"] in subbed_slugs
        label = f"{'✅ Following' if subscribed else '➕ Follow'} {f['name']}"
        buttons.append([InlineKeyboardButton(
            label, callback_data=f"signals:toggle:{f['slug']}"
        )])
    buttons.append(nav_row("dashboard:main"))
    return text, InlineKeyboardMarkup(buttons)


async def signals_command(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Top-level /signals entry — tap-based inline UI."""
    user, ok = await _ensure_user(update)
    if not ok or user is None:
        return

    args = ctx.args or []

    if args:
        if update.message is None:
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
        return

    text, kb = await _build_signals_screen(user["id"])
    if update.callback_query is not None:
        await update.callback_query.message.reply_text(
            text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb,
        )
    elif update.message is not None:
        await update.message.reply_text(
            text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb,
        )


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
        name = _escape_md(s["feed_name"])
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
        desc = _escape_md(f.get("description") or "")
        suffix = f" — {desc}" if desc else ""
        lines.append(
            f"`{f['slug']}` · {_escape_md(f['name'])} · "
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
    """Handle all signals:* inline-keyboard callbacks."""
    q = update.callback_query
    if q is None:
        return
    user, ok = await _ensure_user(update)
    if not ok or user is None:
        return
    await q.answer()

    data = q.data or ""
    parts = data.split(":", 2)

    if len(parts) >= 2 and parts[1] in ("main", "catalog"):
        text, kb = await _build_signals_screen(user["id"])
        await q.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
        return

    if len(parts) == 3 and parts[1] == "toggle":
        slug = _normalise_slug(parts[2])
        if slug is None:
            return
        feed = await get_feed_by_slug(slug)
        if feed is None:
            await q.answer("Feed not found.", show_alert=True)
            return
        subs = await list_user_subscriptions(user["id"])
        subbed_slugs = {s["feed_slug"] for s in subs}
        if slug in subbed_slugs:
            flipped = await unsubscribe(user_id=user["id"], feed_id=feed["id"])
            if flipped:
                await q.answer(f"Unsubscribed from {feed['name']}", show_alert=False)
        else:
            result = await subscribe(user_id=user["id"], feed_id=feed["id"])
            if result == "cap_exceeded":
                await q.answer(
                    f"You have {MAX_SUBSCRIPTIONS_PER_USER} active feeds — "
                    "turn one off before adding another.",
                    show_alert=True,
                )
                return
            elif result == "feed_inactive":
                await q.answer("This feed is paused. Try another one.", show_alert=True)
                return
            else:
                await q.answer(f"Subscribed to {feed['name']}", show_alert=False)
        text, kb = await _build_signals_screen(user["id"])
        await q.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
        return

    if len(parts) == 3 and parts[1] == "off":
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
