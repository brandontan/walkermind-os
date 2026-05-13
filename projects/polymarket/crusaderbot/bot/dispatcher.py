"""Wire all Telegram handlers into the python-telegram-bot Application."""
from __future__ import annotations

import logging

from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters,
)

from .handlers import (
    activation, admin, copy_trade, dashboard, demo_polish, emergency, health as health_h,
    live_gate, market_card, onboarding, my_trades as my_trades_h,
    pnl_insights as pnl_insights_h, portfolio_chart as portfolio_chart_h,
    positions, presets, referral, settings as settings_handler, setup,
    share_card, signal_following, wallet,
)
from .handlers.settings import (
    cap_set_callback, settings_text_input, sl_set_callback, tp_set_callback,
)
from .menus.main import get_menu_route

logger = logging.getLogger(__name__)


async def _text_router(update, ctx):
    """Route plain text consumers in priority order.

    Main menu buttons are checked FIRST so that tapping a button while
    mid-flow (e.g. during a capital-% or CONFIRM prompt) always routes
    correctly instead of producing "Couldn't parse that". Matching a menu
    button clears any pending ``awaiting`` key so the cancelled flow does
    not bleed into the new surface.

    Activation is checked BEFORE setup because both share the same
    ``ctx.user_data['awaiting']`` slot but recognise different values.
    ``setup.text_input`` pops unknown ``awaiting`` values when it
    returns False — if we ran setup first, the user's CONFIRM reply
    after a live-activation flow would have its awaiting flag silently
    cleared before activation ever saw it, and the auto-trade /
    trading-mode flip would be lost. Activation consumes its own values
    here so setup only sees the setup-prompt values it was designed
    for.
    """
    if update.message is None:
        return
    text = (update.message.text or "").strip()
    menu_handler = get_menu_route(text)
    if menu_handler:
        if ctx.user_data:
            ctx.user_data.pop("awaiting", None)
        await menu_handler(update, ctx)
        return
    if await live_gate.text_input(update, ctx):
        return
    if await activation.text_input(update, ctx):
        return
    if await copy_trade.text_input(update, ctx):
        return
    if await settings_text_input(update, ctx):
        return
    if await setup.text_input(update, ctx):
        return


async def _noop_refresh_cb(update, ctx) -> None:
    """noop:refresh — silently acknowledge; caller re-renders if needed."""
    q = update.callback_query
    if q:
        await q.answer()


async def _global_error_handler(update: object, ctx) -> None:
    logger.error("unhandled bot error: %s", ctx.error, exc_info=ctx.error)


def register(app: Application) -> None:
    # Onboarding ConversationHandler — must be first so /start is intercepted
    # before any standalone CommandHandler("start", ...) could match.
    app.add_handler(onboarding.build_onboard_handler())

    # Command handlers
    app.add_handler(CommandHandler("help", onboarding.help_handler))
    app.add_handler(CommandHandler("menu", onboarding.menu_handler))
    # Demo-polish surface — investor-facing, read-only, no guard mutations.
    app.add_handler(CommandHandler("about", demo_polish.about_command))
    app.add_handler(CommandHandler("status", demo_polish.status_command))
    app.add_handler(CommandHandler("demo", demo_polish.demo_command))
    app.add_handler(CommandHandler("dashboard", dashboard.dashboard))
    app.add_handler(CommandHandler("positions", positions.show_positions))
    app.add_handler(CommandHandler("activity", dashboard.activity))
    app.add_handler(CommandHandler("settings", settings_handler.settings_root))
    # Phase 5C preset surface — explicit command alias for the picker, plus a
    # legacy /setup_advanced escape hatch into the raw-strategy menu.
    app.add_handler(CommandHandler("preset", presets.show_preset_picker))
    app.add_handler(CommandHandler("setup_advanced", setup.setup_legacy_root))
    app.add_handler(CommandHandler("emergency", emergency.emergency_root))
    app.add_handler(CommandHandler("admin", admin.admin_root))
    app.add_handler(CommandHandler("allowlist", admin.allowlist_command))
    # R12f operator dashboard / ops plane.
    app.add_handler(CommandHandler("ops_dashboard", admin.ops_dashboard_command))
    app.add_handler(CommandHandler("killswitch", admin.killswitch_command))
    # Demo-readiness operator aliases — map to /killswitch pause / resume
    # so the investor-facing flow ("/kill" → "/resume") goes through the
    # same audited path.
    app.add_handler(CommandHandler("kill", admin.kill_command))
    app.add_handler(CommandHandler("resume", admin.resume_command))
    app.add_handler(CommandHandler("health", health_h.health_command))
    app.add_handler(CommandHandler("jobs", admin.jobs_command))
    app.add_handler(CommandHandler("auditlog", admin.auditlog_command))
    app.add_handler(CommandHandler("unlock", admin.unlock_command))
    # Copy-trade strategy command surface.
    app.add_handler(CommandHandler("copytrade", copy_trade.copy_trade_command))
    # P3c signal-following strategy command surface.
    app.add_handler(CommandHandler("signals", signal_following.signals_command))
    # R12 live-activation + daily-summary opt-in.
    app.add_handler(CommandHandler(
        "live_checklist", activation.live_checklist_command,
    ))
    # Track F — 3-step live opt-in gate.
    app.add_handler(CommandHandler("enable_live", live_gate.enable_live_command))
    app.add_handler(CommandHandler("summary_on", activation.summary_on_command))
    app.add_handler(CommandHandler("summary_off", activation.summary_off_command))
    app.add_handler(CommandHandler("insights", pnl_insights_h.pnl_insights_command))
    app.add_handler(CommandHandler("chart", portfolio_chart_h.chart_command))
    app.add_handler(CommandHandler("market", market_card.market_command))
    app.add_handler(CommandHandler("referral", referral.referral_command))
    # Onboarding-polish command aliases — user-friendly shortcuts.
    app.add_handler(CommandHandler("scan",   signal_following.signals_command))
    app.add_handler(CommandHandler("pnl",    dashboard.dashboard))
    app.add_handler(CommandHandler("close",  positions.show_positions))
    app.add_handler(CommandHandler("trades", my_trades_h.my_trades))
    app.add_handler(CommandHandler("mode",   settings_handler.settings_root))

    # Phase 5F wizard ConversationHandler — must be registered BEFORE the
    # general copytrade: CallbackQueryHandler so it intercepts copytrade:copy:*
    # and copytrade:edit:* entry points first.
    app.add_handler(copy_trade.build_wizard_handler())

    # Phase 5G customize wizard — must be registered BEFORE the general
    # preset: CallbackQueryHandler so it intercepts preset:customize:* and
    # preset:edit entry points first.
    app.add_handler(presets.build_customize_handler())

    # Callback queries
    app.add_handler(CallbackQueryHandler(wallet.wallet_callback, pattern=r"^wallet:"))
    app.add_handler(CallbackQueryHandler(setup.setup_callback,  pattern=r"^setup:"))
    app.add_handler(CallbackQueryHandler(presets.preset_callback,
                                         pattern=r"^preset:"))
    app.add_handler(CallbackQueryHandler(setup.set_strategy,    pattern=r"^set_strategy:"))
    app.add_handler(CallbackQueryHandler(setup.set_risk,        pattern=r"^set_risk:"))
    app.add_handler(CallbackQueryHandler(setup.set_category,    pattern=r"^set_cat:"))
    app.add_handler(CallbackQueryHandler(setup.set_mode,        pattern=r"^set_mode:"))
    app.add_handler(CallbackQueryHandler(setup.set_redeem_mode, pattern=r"^set_redeem:"))
    app.add_handler(CallbackQueryHandler(settings_handler.settings_callback,
                                         pattern=r"^settings:"))
    app.add_handler(CallbackQueryHandler(dashboard.dashboard_nav_cb,
                                         pattern=r"^dashboard:"))
    app.add_handler(CallbackQueryHandler(setup.set_strategy_card, pattern=r"^strategy:"))
    app.add_handler(CallbackQueryHandler(tp_set_callback,         pattern=r"^tp_set:"))
    app.add_handler(CallbackQueryHandler(sl_set_callback,         pattern=r"^sl_set:"))
    app.add_handler(CallbackQueryHandler(cap_set_callback,        pattern=r"^cap_set:"))
    app.add_handler(CallbackQueryHandler(dashboard.autotrade_toggle_cb,
                                         pattern=r"^autotrade:"))
    app.add_handler(CallbackQueryHandler(dashboard.close_position_cb,
                                         pattern=r"^position:close:"))
    app.add_handler(CallbackQueryHandler(positions.force_close_ask,
                                         pattern=r"^position:fc_ask:"))
    app.add_handler(CallbackQueryHandler(positions.force_close_confirm,
                                         pattern=r"^position:fc_(yes|no):"))
    app.add_handler(CallbackQueryHandler(pnl_insights_h.insights_cb,
                                         pattern=r"^insights:"))
    app.add_handler(CallbackQueryHandler(portfolio_chart_h.chart_callback,
                                         pattern=r"^chart:"))
    # Phase 5I My Trades combined view — close + history callbacks.
    app.add_handler(CallbackQueryHandler(my_trades_h.close_ask_cb,
                                         pattern=r"^mytrades:close_ask:"))
    app.add_handler(CallbackQueryHandler(my_trades_h.close_confirm_cb,
                                         pattern=r"^mytrades:close_(yes|no):"))
    app.add_handler(CallbackQueryHandler(my_trades_h.history_cb,
                                         pattern=r"^mytrades:hist:"))
    app.add_handler(CallbackQueryHandler(my_trades_h.back_cb,
                                         pattern=r"^mytrades:back$"))
    app.add_handler(CallbackQueryHandler(emergency.emergency_callback,
                                         pattern=r"^emergency:"))
    app.add_handler(CallbackQueryHandler(admin.admin_callback,  pattern=r"^admin:"))
    app.add_handler(CallbackQueryHandler(admin.ops_dashboard_callback,
                                         pattern=r"^ops:"))
    app.add_handler(CallbackQueryHandler(copy_trade.copy_trade_callback,
                                         pattern=r"^copytrade:"))
    app.add_handler(CallbackQueryHandler(signal_following.signals_callback,
                                         pattern=r"^signals:"))
    app.add_handler(CallbackQueryHandler(market_card.market_callback,
                                         pattern=r"^market:"))
    # Track F — live gate step 3 buttons.
    app.add_handler(CallbackQueryHandler(live_gate.live_gate_callback,
                                         pattern=r"^live_gate:"))
    # Track I — referral share card button.
    app.add_handler(CallbackQueryHandler(share_card.referral_callback,
                                         pattern=r"^referral:share:"))
    # Onboarding polish — View Dashboard button after paper activation.
    app.add_handler(CallbackQueryHandler(onboarding.view_dashboard_cb,
                                         pattern=r"^onboard:view_dashboard$"))
    # Onboarding v3 — Settings shortcut from welcome screen.
    app.add_handler(CallbackQueryHandler(onboarding.onboard_settings_cb,
                                         pattern=r"^onboard:settings$"))

    # v3 — Portfolio surface callbacks.
    app.add_handler(CallbackQueryHandler(positions.portfolio_callback,
                                         pattern=r"^portfolio:"))

    # v3 — My Trades trade-detail card (from fill notifications).
    app.add_handler(CallbackQueryHandler(my_trades_h.trade_detail_cb,
                                         pattern=r"^mytrades:open:"))

    # v3 — noop:refresh — re-answers silently; screen stays as-is.
    app.add_handler(CallbackQueryHandler(_noop_refresh_cb, pattern=r"^noop:"))

    # Free text — must be last
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _text_router))

    app.add_error_handler(_global_error_handler)
