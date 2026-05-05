"""R12e Settings menu handler.

Top-level ⚙️ Settings surface. Phase 1 ships the auto-redeem mode
toggle (blueprint §9). Other rows (notifications, 2FA, language,
privacy, advanced) are placeholders deferred to later lanes.

Tier gating: settings is reachable from any tier — the blueprint
positions Settings as a global account surface rather than a
strategy-config surface, so we do not gate it on Tier 2 (allowlisted)
the way ``setup`` does.
"""
from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ...users import get_settings_for, update_settings, upsert_user
from ..keyboards.settings import autoredeem_settings_picker, settings_menu

logger = logging.getLogger(__name__)


def _redeem_info_text(auto_redeem_mode: str) -> str:
    return (
        "*⚙️ Settings*\n\n"
        f"Auto-Redeem Mode: `{auto_redeem_mode}`\n\n"
        "_Instant uses more gas. Hourly batches redeems for lower cost._"
    )


async def settings_root(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Render the Settings root view."""
    if update.effective_user is None or update.message is None:
        return
    user = await upsert_user(update.effective_user.id, update.effective_user.username)
    s = await get_settings_for(user["id"])
    await update.message.reply_text(
        _redeem_info_text(s["auto_redeem_mode"]),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=settings_menu(s["auto_redeem_mode"]),
    )


async def settings_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle ``settings:*`` callback queries.

    Three sub-actions:
      * ``settings:menu``                → repaint root keyboard
      * ``settings:redeem``              → open the auto-redeem picker
      * ``settings:redeem_set:<choice>`` → apply auto-redeem choice
    """
    q = update.callback_query
    if q is None or update.effective_user is None:
        return
    await q.answer()
    user = await upsert_user(update.effective_user.id, update.effective_user.username)
    data = q.data or ""

    if data == "settings:menu":
        s = await get_settings_for(user["id"])
        await q.message.edit_text(
            _redeem_info_text(s["auto_redeem_mode"]),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=settings_menu(s["auto_redeem_mode"]),
        )
        return

    if data == "settings:redeem":
        s = await get_settings_for(user["id"])
        await q.message.reply_text(
            "Pick auto-redeem mode.\n\n"
            "*Instant* — settle the moment a market resolves "
            "(live trades are gas-spike guarded).\n"
            "*Hourly* — wait for the hourly batch (default, lower gas).",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=autoredeem_settings_picker(s["auto_redeem_mode"]),
        )
        return

    if data.startswith("settings:redeem_set:"):
        choice = data.split(":", 2)[-1]
        if choice not in ("instant", "hourly"):
            return
        await update_settings(user["id"], auto_redeem_mode=choice)
        await q.message.edit_reply_markup(
            reply_markup=autoredeem_settings_picker(choice),
        )
        await q.message.reply_text(
            f"✅ Auto-redeem mode set to *{choice}*.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
