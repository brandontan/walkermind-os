"""Phase 5 UX Rebuild — handler registration.

CRITICAL: ALL primary menu callbacks (menu:*) are registered at group=-1
BEFORE any ConversationHandlers. This prevents nav breakage when a user
taps a main menu button from inside a wizard or ConversationHandler state.
"""
from __future__ import annotations

import logging

from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters,
)

from .handlers import (
    activation, admin, copy_trade, demo_polish, emergency,
    health as health_h, live_gate, market_card,
    pnl_insights as pnl_insights_h, portfolio_chart as portfolio_chart_h,
    positions, referral, settings as settings_handler, setup,
    share_card, signal_following,
)
from .handlers.autotrade import autotrade_callback, show_autotrade
from .handlers.dashboard import (
    autotrade_toggle_cb, close_position_cb, dashboard, dashboard_nav_cb,
    show_dashboard_for_cb, activity,
)
from .handlers.emergency import emergency_callback, emergency_root, emergency_root_cb
from .handlers.presets import preset_callback
from .handlers.start import build_start_handler, help_command
from .handlers.trades import (
    back_cb, cancel_close_cb, close_ask_cb, close_confirm_cb,
    close_confirm_legacy_cb, history_cb, my_trades, show_trades,
    trade_detail_cb,
)
from .handlers.wallet import wallet_callback, wallet_root, wallet_root_cb
from .handlers.settings import (
    cap_set_callback, settings_text_input, sl_set_callback, tp_set_callback,
)
from .menus.main import get_menu_route

logger = logging.getLogger(__name__)


async def _menu_nav_cb(update, ctx) -> None:
    """group=-1 — fires before ConversationHandler states.

    Routes menu:* callback_data to the correct surface so tapping a primary
    nav button from inside any wizard always works.
    """
    q = update.callback_query
    if q is None:
        return
    sub = (q.data or "").split(":", 1)[-1]
    if sub == "portfolio":
        # show_portfolio calls q.answer() itself — dispatch before the global
        # pre-answer below to avoid double-ACK (BadRequest from Telegram).
        from .handlers.positions import show_portfolio
        await show_portfolio(update, ctx)
        return
    await q.answer()
    if sub == "dashboard":
        await show_dashboard_for_cb(update, ctx)
    elif sub == "autotrade":
        await show_autotrade(update, ctx)
    elif sub == "wallet":
        await wallet_root_cb(update, ctx)
    elif sub == "trades":
        await show_trades(update, ctx)
    elif sub == "emergency":
        await emergency_root_cb(update, ctx)
    elif sub == "settings":
        await settings_handler.settings_hub_root(update, ctx)


async def _noop_refresh_cb(update, ctx) -> None:
    q = update.callback_query
    if not q:
        return
    await q.answer()
    await show_dashboard_for_cb(update, ctx, refresh=True)


async def _nav_cb(update, ctx) -> None:
    """Tactical Terminal polish — handles `nav:*` callback prefixes.

    The new `_common.py` keyboard helpers emit:
      - nav:home    → return to dashboard
      - nav:back    → re-render dashboard (handlers can override per-flow)
      - nav:refresh → silent refresh + re-render dashboard
      - nav:noop    → silently absorb (used by pagination indicator)
    """
    q = update.callback_query
    if q is None:
        return
    await q.answer()
    sub = (q.data or "").split(":", 1)[-1]
    if sub == "noop":
        return
    if sub == "refresh":
        await show_dashboard_for_cb(update, ctx, refresh=True)
        return
    # nav:home and nav:back default to the main dashboard surface.
    await show_dashboard_for_cb(update, ctx)


async def _global_error_handler(update: object, ctx) -> None:
    logger.error("unhandled bot error: %s", ctx.error, exc_info=ctx.error)


async def _text_router(update, ctx) -> None:
    """Route plain text in priority order. Menu buttons clear pending wizard state."""
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


def register(app: Application) -> None:
    # ── group=-1: primary nav — fires BEFORE ConversationHandlers ────────────────
    app.add_handler(CallbackQueryHandler(_menu_nav_cb, pattern=r"^menu:"), group=-1)
    # Tactical Terminal polish — nav:* prefix for new keyboards (home/back/refresh/noop).
    app.add_handler(CallbackQueryHandler(_nav_cb, pattern=r"^nav:"), group=-1)
    # Persistent keyboard text buttons — interrupt any ConversationHandler state
    app.add_handler(MessageHandler(
        filters.Regex(r"^📊 Dashboard$"), dashboard), group=-1)
    app.add_handler(MessageHandler(
        filters.Regex(r"^🤖 Auto-Trade$"), show_autotrade), group=-1)
    app.add_handler(MessageHandler(
        filters.Regex(r"^💰 Wallet$"), wallet_root), group=-1)
    app.add_handler(MessageHandler(
        filters.Regex(r"^📈 My Trades$"), show_trades), group=-1)
    app.add_handler(MessageHandler(
        filters.Regex(r"^🚨 Emergency$"), emergency_root), group=-1)

    # ── Phase 5 start / onboarding ConversationHandler ─────────────────────────
    app.add_handler(build_start_handler())

    # ── Command handlers ────────────────────────────────────────────────────────
    app.add_handler(CommandHandler("help",            help_command))
    app.add_handler(CommandHandler("menu",            show_dashboard_for_cb))
    app.add_handler(CommandHandler("about",           demo_polish.about_command))
    app.add_handler(CommandHandler("status",          demo_polish.status_command))
    app.add_handler(CommandHandler("demo",            demo_polish.demo_command))
    app.add_handler(CommandHandler("dashboard",       dashboard))
    app.add_handler(CommandHandler("positions",       positions.show_positions))
    app.add_handler(CommandHandler("activity",        activity))
    app.add_handler(CommandHandler("settings",        settings_handler.settings_root))
    app.add_handler(CommandHandler("preset",          show_autotrade))
    app.add_handler(CommandHandler("setup_advanced",  setup.setup_legacy_root))
    app.add_handler(CommandHandler("emergency",       emergency_root))
    app.add_handler(CommandHandler("admin",           admin.admin_root))
    app.add_handler(CommandHandler("allowlist",       admin.allowlist_command))
    app.add_handler(CommandHandler("ops_dashboard",   admin.ops_dashboard_command))
    app.add_handler(CommandHandler("killswitch",      admin.killswitch_command))
    app.add_handler(CommandHandler("kill",            admin.kill_command))
    app.add_handler(CommandHandler("resume",          admin.resume_command))
    app.add_handler(CommandHandler("health",          health_h.health_command))
    app.add_handler(CommandHandler("jobs",            admin.jobs_command))
    app.add_handler(CommandHandler("auditlog",        admin.auditlog_command))
    app.add_handler(CommandHandler("unlock",          admin.unlock_command))
    app.add_handler(CommandHandler("resetonboard",    admin.resetonboard_command))
    app.add_handler(CommandHandler("copytrade",       copy_trade.copy_trade_command))
    app.add_handler(CommandHandler("signals",         signal_following.signals_command))
    app.add_handler(CommandHandler("live_checklist",  activation.live_checklist_command))
    app.add_handler(CommandHandler("enable_live",     live_gate.enable_live_command))
    app.add_handler(CommandHandler("summary_on",      activation.summary_on_command))
    app.add_handler(CommandHandler("summary_off",     activation.summary_off_command))
    app.add_handler(CommandHandler("insights",        pnl_insights_h.pnl_insights_command))
    app.add_handler(CommandHandler("chart",           portfolio_chart_h.chart_command))
    app.add_handler(CommandHandler("market",          market_card.market_command))
    app.add_handler(CommandHandler("referral",        referral.referral_command))
    # NB: aliases (/scan, /pnl, /close, /trades, /mode) consolidated away —
    # use canonical commands (/signals, /dashboard, /positions, /activity,
    # /settings). One alias kept for back-compat:
    app.add_handler(CommandHandler("trades",          my_trades))

    # ── Phase 5F copy-trade wizard (before general copytrade: handler) ──────────
    app.add_handler(copy_trade.build_wizard_handler())

    # ── Phase 5 customize wizard (before general preset: handler) ───────────────
    from .handlers.customize import build_customize_handler
    app.add_handler(build_customize_handler())

    # Legacy presets wizard (kept for non-rewritten flows)
    from .handlers.presets import build_customize_handler as legacy_customize
    app.add_handler(legacy_customize())

    # ── Callback query handlers ─────────────────────────────────────────────────

    # Phase 5 — autotrade (preset picker + confirm + active status)
    app.add_handler(CallbackQueryHandler(autotrade_callback,
                                         pattern=r"^p5:(preset|confirm|active):"))

    # Phase 5 — emergency
    app.add_handler(CallbackQueryHandler(emergency_callback,
                                         pattern=r"^p5:emergency:"))

    # Phase 5 — close position flow
    app.add_handler(CallbackQueryHandler(close_ask_cb,
                                         pattern=r"^close_position:[^c]"))
    app.add_handler(CallbackQueryHandler(close_confirm_cb,
                                         pattern=r"^close_position:confirm:"))
    app.add_handler(CallbackQueryHandler(cancel_close_cb,
                                         pattern=r"^p5:trades:cancel_close$"))
    app.add_handler(CallbackQueryHandler(history_cb,
                                         pattern=r"^p5:trades:history$"))

    # Phase 5 — wallet
    app.add_handler(CallbackQueryHandler(wallet_callback, pattern=r"^p5:wallet:"))

    # Legacy wallet callbacks
    app.add_handler(CallbackQueryHandler(wallet_callback, pattern=r"^wallet:"))

    # Legacy setup / strategy callbacks
    app.add_handler(CallbackQueryHandler(setup.setup_callback,  pattern=r"^setup:"))
    app.add_handler(CallbackQueryHandler(preset_callback,        pattern=r"^preset:"))
    app.add_handler(CallbackQueryHandler(setup.set_strategy,    pattern=r"^set_strategy:"))
    app.add_handler(CallbackQueryHandler(setup.set_risk,        pattern=r"^set_risk:"))
    app.add_handler(CallbackQueryHandler(setup.set_category,    pattern=r"^set_cat:"))
    app.add_handler(CallbackQueryHandler(setup.set_mode,        pattern=r"^set_mode:"))
    app.add_handler(CallbackQueryHandler(setup.set_redeem_mode, pattern=r"^set_redeem:"))

    # Settings callbacks
    app.add_handler(CallbackQueryHandler(settings_handler.settings_callback,
                                         pattern=r"^settings:"))

    # Dashboard legacy callbacks
    app.add_handler(CallbackQueryHandler(dashboard_nav_cb,      pattern=r"^dashboard:"))
    app.add_handler(CallbackQueryHandler(setup.set_strategy_card, pattern=r"^strategy:"))
    app.add_handler(CallbackQueryHandler(tp_set_callback,         pattern=r"^tp_set:"))
    app.add_handler(CallbackQueryHandler(sl_set_callback,         pattern=r"^sl_set:"))
    app.add_handler(CallbackQueryHandler(cap_set_callback,        pattern=r"^cap_set:"))
    app.add_handler(CallbackQueryHandler(autotrade_toggle_cb,     pattern=r"^autotrade:"))

    # Legacy close position callbacks
    app.add_handler(CallbackQueryHandler(close_ask_cb,
                                         pattern=r"^position:close:"))
    app.add_handler(CallbackQueryHandler(positions.force_close_ask,
                                         pattern=r"^position:fc_ask:"))
    app.add_handler(CallbackQueryHandler(positions.force_close_confirm,
                                         pattern=r"^position:fc_(yes|no):"))

    app.add_handler(CallbackQueryHandler(pnl_insights_h.insights_cb,
                                         pattern=r"^insights:"))
    app.add_handler(CallbackQueryHandler(portfolio_chart_h.chart_callback,
                                         pattern=r"^chart:"))

    # Legacy my_trades callbacks (backward compat)
    app.add_handler(CallbackQueryHandler(close_ask_cb,
                                         pattern=r"^mytrades:close_ask:"))
    app.add_handler(CallbackQueryHandler(close_confirm_legacy_cb,
                                         pattern=r"^mytrades:close_(yes|no):"))
    app.add_handler(CallbackQueryHandler(history_cb,
                                         pattern=r"^mytrades:hist:"))
    app.add_handler(CallbackQueryHandler(back_cb,
                                         pattern=r"^mytrades:back$"))

    # Legacy emergency callbacks
    app.add_handler(CallbackQueryHandler(emergency_callback,   pattern=r"^emergency:"))

    app.add_handler(CallbackQueryHandler(admin.admin_callback,  pattern=r"^admin:"))
    app.add_handler(CallbackQueryHandler(admin.ops_dashboard_callback, pattern=r"^ops:"))
    app.add_handler(CallbackQueryHandler(copy_trade.copy_trade_callback, pattern=r"^copytrade:"))
    app.add_handler(CallbackQueryHandler(signal_following.signals_callback, pattern=r"^signals:"))
    app.add_handler(CallbackQueryHandler(market_card.market_callback, pattern=r"^market:"))
    app.add_handler(CallbackQueryHandler(live_gate.live_gate_callback, pattern=r"^live_gate:"))
    app.add_handler(CallbackQueryHandler(share_card.referral_callback, pattern=r"^referral:share:"))

    # Onboarding callbacks (legacy onboarding.py still used by admin resetonboard)
    from .handlers import onboarding
    app.add_handler(CallbackQueryHandler(onboarding.view_dashboard_cb,
                                         pattern=r"^onboard:view_dashboard$"))
    app.add_handler(CallbackQueryHandler(onboarding.onboard_settings_cb,
                                         pattern=r"^onboard:settings$"))

    # Portfolio surface callbacks
    app.add_handler(CallbackQueryHandler(positions.portfolio_callback, pattern=r"^portfolio:"))

    # Trade detail
    app.add_handler(CallbackQueryHandler(trade_detail_cb, pattern=r"^mytrades:open:"))

    # noop:refresh
    app.add_handler(CallbackQueryHandler(_noop_refresh_cb, pattern=r"^noop:"))

    # Free text — must be last
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _text_router))

    app.add_error_handler(_global_error_handler)
