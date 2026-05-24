"""MVP Help handler — explainer screens, FAQ, support."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from ... import messages_mvp as mvp
from ...keyboards_v2.mvp import help as kb
from ._send import callback_parts, send_or_edit

log = logging.getLogger(__name__)


async def show_home(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await send_or_edit(update, mvp.render_help_home(), kb.home_kb())


async def show_quick_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await send_or_edit(update, mvp.render_help_quick_start_guide(), kb.quick_start_kb())


async def show_how_auto_trade(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await send_or_edit(update, mvp.render_help_how_auto_trade(), kb.how_auto_trade_kb())


async def show_how_copy_wallet(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await send_or_edit(update, mvp.render_help_how_copy_wallet(), kb.how_copy_wallet_kb())


async def show_safety(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await send_or_edit(update, mvp.render_help_safety(), kb.safety_kb())


async def show_faq(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await send_or_edit(update, mvp.render_help_faq(), kb.faq_kb())


async def show_support(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await send_or_edit(update, mvp.render_help_support(), kb.support_kb())


async def _help_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    parts = callback_parts(update)
    screen = parts[1] if len(parts) > 1 else "home"
    if screen == "home":
        await show_home(update, ctx); return
    if screen == "quick_start":
        await show_quick_start(update, ctx); return
    if screen == "auto":
        await show_how_auto_trade(update, ctx); return
    if screen == "copy_wallet":
        await show_how_copy_wallet(update, ctx); return
    if screen == "safety":
        await show_safety(update, ctx); return
    if screen == "faq":
        await show_faq(update, ctx); return
    if screen == "support":
        await show_support(update, ctx); return
    await show_home(update, ctx)


def attach(app: Application) -> None:
    app.add_handler(CommandHandler("help", show_home))
    app.add_handler(CallbackQueryHandler(_help_cb, pattern=r"^help:"))
