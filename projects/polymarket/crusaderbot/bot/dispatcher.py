"""Telegram dispatcher: builds Application, registers /start, /status, /allowlist."""
from __future__ import annotations

from functools import partial

import asyncpg
import structlog
from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

from ..config import Settings, settings
from ..services.allowlist import get_user_tier, tier_label
from .handlers.admin import handle_allowlist
from .handlers.onboarding import handle_start
from .handlers.wallet import handle_deposit, handle_wallet

log = structlog.get_logger(__name__)


async def status_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Show caller's tier + system guard states. Unrestricted (any tier can call)."""
    if update.effective_message is None or update.effective_user is None:
        return

    caller_tier = await get_user_tier(update.effective_user.id)

    lines = [f"Your access tier: {tier_label(caller_tier)}", ""]
    lines.append("Guard states:")
    for name, value in settings.guard_states.items():
        marker = "✅ ON" if value else "⚪ OFF"
        lines.append(f"- {name}: {marker}")
    mode = "LIVE" if settings.ENABLE_LIVE_TRADING else "PAPER"
    lines.append("")
    lines.append(f"Mode: {mode}")
    lines.append(f"Env: {settings.APP_ENV}")
    await update.effective_message.reply_text("\n".join(lines))


def setup_handlers(
    app: Application,
    *,
    db_pool: asyncpg.Pool,
    config: Settings,
) -> None:
    """Register handlers. db_pool/config are bound via partial as needed.

    Both required keyword args fail fast at call time if missing.
    """
    bound_start = partial(handle_start, pool=db_pool, config=config)
    bound_allowlist = partial(handle_allowlist, config=config)
    bound_wallet = partial(handle_wallet, pool=db_pool, config=config)
    bound_deposit = partial(handle_deposit, pool=db_pool, config=config)
    app.add_handler(CommandHandler("start", bound_start))
    app.add_handler(CommandHandler("status", status_handler))
    app.add_handler(CommandHandler("allowlist", bound_allowlist))
    app.add_handler(CommandHandler("wallet", bound_wallet))
    app.add_handler(CommandHandler("deposit", bound_deposit))
    log.info(
        "bot.handlers_registered",
        commands=["start", "status", "allowlist", "wallet", "deposit"],
    )


def get_application() -> Application:
    return ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).build()
