"""Wire all Telegram handlers into the python-telegram-bot Application."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters,
)

from .handlers import (
    admin, dashboard, emergency, onboarding, positions,
    settings as settings_handler, setup, wallet,
)
from .menus.main import get_menu_route

logger = logging.getLogger(__name__)


async def _text_router(update, ctx):
    """Route plain text: first to setup awaiting-prompts, then to menu buttons."""
    if await setup.text_input(update, ctx):
        return
    if update.message is None:
        return
    text = (update.message.text or "").strip()
    handler = get_menu_route(text)
    if handler:
        await handler(update, ctx)


async def _global_error_handler(update: object, ctx) -> None:
    logger.error("unhandled bot error: %s", ctx.error, exc_info=ctx.error)


def register(app: Application) -> None:
    # Command handlers
    app.add_handler(CommandHandler("start", onboarding.start_handler))
    app.add_handler(CommandHandler("help", onboarding.help_handler))
    app.add_handler(CommandHandler("menu", onboarding.menu_handler))
    app.add_handler(CommandHandler("dashboard", dashboard.dashboard))
    app.add_handler(CommandHandler("positions", positions.show_positions))
    app.add_handler(CommandHandler("activity", dashboard.activity))
    app.add_handler(CommandHandler("emergency", emergency.emergency_root))
    app.add_handler(CommandHandler("admin", admin.admin_root))
    app.add_handler(CommandHandler("allowlist", admin.allowlist_command))
    # R12f operator dashboard / ops plane.
    app.add_handler(CommandHandler("ops_dashboard", admin.ops_dashboard_command))
    app.add_handler(CommandHandler("killswitch", admin.killswitch_command))
    app.add_handler(CommandHandler("jobs", admin.jobs_command))
    app.add_handler(CommandHandler("auditlog", admin.auditlog_command))

    # Callback queries
    app.add_handler(CallbackQueryHandler(wallet.wallet_callback, pattern=r"^wallet:"))
    app.add_handler(CallbackQueryHandler(setup.setup_callback,  pattern=r"^setup:"))
    app.add_handler(CallbackQueryHandler(setup.set_strategy,    pattern=r"^set_strategy:"))
    app.add_handler(CallbackQueryHandler(setup.set_risk,        pattern=r"^set_risk:"))
    app.add_handler(CallbackQueryHandler(setup.set_category,    pattern=r"^set_cat:"))
    app.add_handler(CallbackQueryHandler(setup.set_mode,        pattern=r"^set_mode:"))
    app.add_handler(CallbackQueryHandler(setup.set_redeem_mode, pattern=r"^set_redeem:"))
    app.add_handler(CallbackQueryHandler(settings_handler.settings_callback,
                                         pattern=r"^settings:"))
    app.add_handler(CallbackQueryHandler(dashboard.autotrade_toggle_cb,
                                         pattern=r"^autotrade:"))
    app.add_handler(CallbackQueryHandler(dashboard.close_position_cb,
                                         pattern=r"^position:close:"))
    app.add_handler(CallbackQueryHandler(positions.force_close_ask,
                                         pattern=r"^position:fc_ask:"))
    app.add_handler(CallbackQueryHandler(positions.force_close_confirm,
                                         pattern=r"^position:fc_(yes|no):"))
    app.add_handler(CallbackQueryHandler(emergency.emergency_callback,
                                         pattern=r"^emergency:"))
    app.add_handler(CallbackQueryHandler(admin.admin_callback,  pattern=r"^admin:"))
    app.add_handler(CallbackQueryHandler(admin.ops_dashboard_callback,
                                         pattern=r"^ops:"))

    # Free text — must be last
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _text_router))

    app.add_error_handler(_global_error_handler)
