"""MVP Onboarding flow — new user → wallet init → preset → deposit prompt.

Returning users skip straight to the Dashboard (blueprint 19.1).
"""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from ... import messages_mvp as mvp
from ...keyboards.mvp._common import main_menu_kb
from ...keyboards.mvp.onboarding import (
    deposit_prompt_kb,
    wallet_ready_kb,
    welcome_kb,
)
from . import _users, dashboard as dash
from ._send import send_or_edit

log = logging.getLogger(__name__)


async def _classify(telegram_user) -> tuple[bool, str | None]:
    """Return (is_returning, wallet_address_short). Defensive — DB errors
    treat the caller as a new user so they always see Welcome."""
    u = await _users.fetch_user(telegram_user.id, telegram_user.username)
    if u is None:
        return False, None
    settings = await _users.fetch_settings(u["id"])
    configured = bool(u.get("auto_trade_enabled")) or bool(settings.get("active_preset"))
    wallet_addr: str | None = None
    try:
        from ....database import get_pool  # type: ignore
        pool = get_pool()
        async with pool.acquire() as conn:
            addr = await conn.fetchval(
                "SELECT deposit_address FROM wallets WHERE user_id=$1",
                u["id"],
            )
            if addr:
                wallet_addr = str(addr)
    except Exception as exc:  # noqa: BLE001
        log.debug("wallet address fetch unavailable: %s", exc)
    return configured, wallet_addr


async def start_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None:
        return
    returning, _addr = await _classify(user)
    if returning:
        # Re-attach persistent keyboard in case it was lost (e.g. app reinstall).
        msg = update.effective_message
        if msg is not None:
            await msg.reply_text(
                ".",
                reply_markup=main_menu_kb(auto_on=True, paused=False, open_count=0, configured=returning),
            )
        await dash.show_dashboard(update, ctx)
        return
    user_name = (user.first_name or "trader").strip() or "trader"
    await send_or_edit(update, mvp.render_welcome(user_name=user_name), welcome_kb())


async def show_wallet_ready(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    short = "0x12...ab9"
    if user is not None:
        _conf, addr = await _classify(user)
        if addr and len(addr) >= 12:
            short = f"{addr[:5]}...{addr[-4:]}"
    await send_or_edit(update, mvp.render_wallet_ready(address_short=short), wallet_ready_kb())


async def show_deposit_prompt(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await send_or_edit(update, mvp.render_deposit_prompt(), deposit_prompt_kb())


def attach(app: Application) -> None:
    # MVP /start owns the entry point; legacy build_start_handler keeps its
    # other slash commands but MVP's earlier registration wins for /start.
    app.add_handler(CommandHandler("start", start_command))
