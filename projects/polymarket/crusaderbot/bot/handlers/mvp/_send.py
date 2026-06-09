"""Shared MVP handler helpers: safe send/edit, callback parsing."""
from __future__ import annotations

import logging
from typing import Optional, Union

from telegram import InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

log = logging.getLogger(__name__)


async def send_or_edit(
    update: Update,
    text: str,
    keyboard: Optional[Union[InlineKeyboardMarkup, ReplyKeyboardMarkup]] = None,
    *,
    parse_mode: Optional[str] = "HTML",
) -> None:
    """Send a new message on /command, edit in place on callback.

    ReplyKeyboardMarkup cannot be passed to edit_message_text; when detected
    the function always uses reply_text so the persistent keyboard attaches.

    Telegram rejects edits when the new payload is identical to the existing
    message; that BadRequest is logged at DEBUG and swallowed so refresh
    presses do not surface errors to the user.
    """
    if isinstance(keyboard, ReplyKeyboardMarkup):
        q = update.callback_query
        if q is not None:
            try:
                await q.answer()
            except BadRequest:
                pass
        msg = update.effective_message
        if msg is not None:
            await msg.reply_text(text=text, reply_markup=keyboard, parse_mode=parse_mode)
        return
    q = update.callback_query
    if q is not None:
        try:
            await q.answer()
        except BadRequest:
            pass
        try:
            await q.edit_message_text(text=text, reply_markup=keyboard, parse_mode=parse_mode)
            return
        except BadRequest as exc:
            if "message is not modified" in str(exc).lower():
                return
            log.debug("edit failed, falling back to send: %s", exc)
            if q.message is not None:
                await q.message.reply_text(text=text, reply_markup=keyboard, parse_mode=parse_mode)
                return
            raise
    msg = update.effective_message
    if msg is not None:
        await msg.reply_text(text=text, reply_markup=keyboard, parse_mode=parse_mode)


def callback_tail(update: Update) -> str:
    """Return the suffix after the prefix from `prefix:suffix:...` callback data."""
    q = update.callback_query
    if q is None or not q.data:
        return ""
    parts = q.data.split(":", 2)
    return parts[2] if len(parts) >= 3 else ""


def callback_parts(update: Update) -> list[str]:
    q = update.callback_query
    if q is None or not q.data:
        return []
    return q.data.split(":")


# ── Navigation stack helpers ──────────────────────────────────────────────────
# Each MVP surface pushes its own callback_data prefix onto the stack so that
# nav:back can return to the correct parent instead of always going to dashboard.

_NAV_STACK_KEY = "mvp_nav_stack"
_MAX_STACK_DEPTH = 8


def nav_push(ctx, callback_prefix: str) -> None:
    """Push a surface identifier onto the per-user navigation stack."""
    if ctx.user_data is None:
        return
    stack: list[str] = ctx.user_data.get(_NAV_STACK_KEY) or []
    if not stack or stack[-1] != callback_prefix:
        stack.append(callback_prefix)
    ctx.user_data[_NAV_STACK_KEY] = stack[-_MAX_STACK_DEPTH:]


def nav_pop(ctx) -> str | None:
    """Pop and return the previous surface identifier, or None if stack is empty."""
    if ctx.user_data is None:
        return None
    stack: list[str] = ctx.user_data.get(_NAV_STACK_KEY) or []
    if len(stack) > 1:
        stack.pop()
        ctx.user_data[_NAV_STACK_KEY] = stack
        return stack[-1]
    return None


def nav_clear(ctx) -> None:
    if ctx.user_data is not None:
        ctx.user_data[_NAV_STACK_KEY] = []
