"""WARP-57 Telegram UX MVP v1 — handler registration.

MVP UX (`bot/handlers/mvp/*`) handlers are attached FIRST so they take
precedence over legacy callback handlers that share a prefix. Legacy
handlers stay registered as fallbacks for admin, emergency, copy-trade
wizard, live-gate, and other non-MVP surfaces (blueprint scope: UX only,
domain/services untouched).
"""
from __future__ import annotations

import logging
import re

from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters,
)

_DYNAMIC_TRADES_RE = re.compile(r"^💼 Trades \(\d+\)$")

from .handlers import (
    activation, admin, copy_trade, demo_polish, emergency,
    health as health_h, live_gate, market_card,
    pnl_insights as pnl_insights_h, portfolio_chart as portfolio_chart_h,
    positions, referral, settings as settings_handler, setup,
    share_card, signal_following, strategy as strategy_handler,
)
from .handlers.autotrade import autotrade_callback, show_autotrade
from .handlers.dashboard import (
    autotrade_toggle_cb, dashboard, dashboard_nav_cb,
    show_dashboard_for_cb, activity,
)
from .handlers.emergency import emergency_callback, emergency_root, emergency_root_cb
from .handlers.tg_power_mode import tg_power_mode_cb
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

# WARP-57 MVP v1 handlers — full IA + hierarchy tree UX.
from .handlers.mvp import dashboard as mvp_dashboard
from .handlers.mvp import autotrade as mvp_autotrade
from .handlers.mvp import copy_wallet as mvp_copy_wallet
from .handlers.mvp import portfolio as mvp_portfolio
from .handlers.mvp import markets as mvp_markets
from .handlers.mvp import settings as mvp_settings
from .handlers.mvp import help as mvp_help
from .handlers.mvp import onboarding as mvp_onboarding

logger = logging.getLogger(__name__)


async def _menu_nav_cb(update, ctx) -> None:
    """group=-1 — fires before ConversationHandler states.

    `menu:*` callback_data now routes to the MVP v1 hierarchy-tree surfaces
    (WARP-57). Wallet / emergency / trades remain on their legacy backends
    since those surfaces stay live for admin and runtime ops.
    """
    q = update.callback_query
    if q is None:
        return
    sub = (q.data or "").split(":", 1)[-1]
    # MVP v1 main menu routes — InlineKeyboardMarkup only, blueprint 7.2.
    if sub in {"dashboard", "home"}:
        await mvp_dashboard.show_dashboard(update, ctx); return
    if sub == "autotrade":
        await mvp_autotrade.show_home(update, ctx); return
    if sub in {"copy", "copy_wallet"}:
        await mvp_copy_wallet.show_home(update, ctx); return
    if sub in {"portfolio", "positions"}:
        await mvp_portfolio.show_home(update, ctx); return
    if sub == "markets":
        await mvp_markets.show_home(update, ctx); return
    if sub == "settings":
        await mvp_settings.show_home(update, ctx); return
    if sub == "help":
        await mvp_help.show_home(update, ctx); return
    # Non-MVP legacy surfaces kept live for admin/runtime ops.
    await q.answer()
    if sub == "wallet":
        await wallet_root_cb(update, ctx)
    elif sub == "trades":
        await show_trades(update, ctx)
    elif sub == "emergency":
        await emergency_root_cb(update, ctx)


async def _noop_refresh_cb(update, ctx) -> None:
    q = update.callback_query
    if not q:
        return
    await q.answer()
    await show_dashboard_for_cb(update, ctx, refresh=True)


async def _nav_cb(update, ctx) -> None:
    """`nav:*` global navigation — back / home / refresh / cancel / noop.

    All MVP keyboards emit these prefixes. Default fallback is the MVP
    dashboard surface (blueprint 6.x).
    """
    q = update.callback_query
    if q is None:
        return
    await q.answer()
    sub = (q.data or "").split(":", 1)[-1]
    if sub == "noop":
        return
    if sub in {"home", "back", "refresh", "cancel"}:
        # Back/cancel fall through to the dashboard for MVP — flows that
        # need finer-grained back behavior maintain their own stack and
        # route directly.
        await mvp_dashboard.show_dashboard(update, ctx)
        return
    await mvp_dashboard.show_dashboard(update, ctx)


async def _global_error_handler(update: object, ctx) -> None:
    logger.error("unhandled bot error: %s", ctx.error, exc_info=ctx.error)


async def _text_router(update, ctx) -> None:
    """Route plain text in priority order. Menu buttons clear pending wizard state."""
    if update.message is None:
        return
    text = (update.message.text or "").strip()
    # Dynamic 💼 Trades (N) label — visible response already sent by the
    # group=-1 MessageHandler above. Short-circuit so wizard text handlers
    # don't misprocess the tap.
    if _DYNAMIC_TRADES_RE.match(text):
        if ctx.user_data:
            ctx.user_data.pop("awaiting", None)
        return
    menu_handler = get_menu_route(text)
    if menu_handler:
        if ctx.user_data:
            ctx.user_data.pop("awaiting", None)
        await menu_handler(update, ctx)
        return
    # MVP copy-wallet flow gets first dibs on free text — it captures pasted
    # wallet addresses while in the await_address step (WARP-57).
    if await mvp_copy_wallet.text_input(update, ctx):
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
    # ── WARP-57 MVP v1 — attached FIRST so MVP prefixes win over legacy ────────
    mvp_dashboard.attach(app)
    mvp_autotrade.attach(app)
    mvp_copy_wallet.attach(app)
    mvp_portfolio.attach(app)
    mvp_markets.attach(app)
    mvp_settings.attach(app)
    mvp_help.attach(app)
    # Onboarding /start must register AFTER mvp_dashboard.attach so it wins.
    mvp_onboarding.attach(app)

    # ── group=-1: primary nav — fires BEFORE ConversationHandlers ────────────────
    app.add_handler(CallbackQueryHandler(_menu_nav_cb, pattern=r"^menu:"), group=-1)
    # nav:* prefix — MVP _common.py keyboard helpers emit nav:home/back/refresh/cancel/noop.
    app.add_handler(CallbackQueryHandler(_nav_cb, pattern=r"^nav:"), group=-1)
    # Persistent reply-keyboard text taps — route to MVP surfaces (WARP-57).
    # Legacy users with a residual ReplyKeyboard still get routed correctly
    # into the new hierarchy-tree UX.
    app.add_handler(MessageHandler(
        filters.Regex(r"^(📊 )?Dashboard$"), mvp_dashboard.show_dashboard), group=-1)
    app.add_handler(MessageHandler(
        filters.Regex(r"^🤖 (Auto-Trade|Auto Trade)$"), mvp_autotrade.show_home), group=-1)
    app.add_handler(MessageHandler(
        filters.Regex(r"^💰 Wallet$"), wallet_root), group=-1)
    app.add_handler(MessageHandler(
        filters.Regex(r"^💼 Portfolio$"), mvp_portfolio.show_home), group=-1)
    app.add_handler(MessageHandler(
        filters.Regex(r"^💼 Trades \(\d+\)$"), mvp_portfolio.show_positions), group=-1)
    app.add_handler(MessageHandler(
        filters.Regex(r"^⚙️ Settings$"), mvp_settings.show_home), group=-1)
    app.add_handler(MessageHandler(
        filters.Regex(r"^❓ Help$"), mvp_help.show_home), group=-1)
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
    app.add_handler(CommandHandler("strategy",        strategy_handler.strategy_cmd))
    app.add_handler(CommandHandler("risk",            strategy_handler.risk_cmd))
    app.add_handler(CommandHandler("paper",           strategy_handler.paper_cmd))
    app.add_handler(CommandHandler("config",          strategy_handler.config_cmd))

    # ── 8-step copy-trade wizard (registered BEFORE the 3-step wizard) ──────────
    app.add_handler(copy_trade.build_new_copy_wizard_handler())

    # ── Phase 5F copy-trade wizard (edit-only entry after new wizard) ────────────
    app.add_handler(copy_trade.build_wizard_handler())

    # ── Phase 5 customize wizard (before general preset: handler) ───────────────
    from .handlers.customize import build_customize_handler
    app.add_handler(build_customize_handler())

    # Legacy presets wizard (kept for non-rewritten flows)
    from .handlers.presets import build_customize_handler as legacy_customize
    app.add_handler(legacy_customize())

    # ── Callback query handlers ─────────────────────────────────────────────────

    # Phase 5 — autotrade (preset picker + confirm + active status + menu)
    app.add_handler(CallbackQueryHandler(autotrade_callback,
                                         pattern=r"^(p5:(preset|confirm|active):|auto_trade:)"))

    # Phase 5 — emergency
    app.add_handler(CallbackQueryHandler(emergency_callback,
                                         pattern=r"^p5:emergency:"))

    # Phase 5 — close position flow
    app.add_handler(CallbackQueryHandler(close_ask_cb,
                                         pattern=r"^close_position:(?!confirm:)"))
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

    # Telegram Power Mode — trade notification inline buttons
    app.add_handler(CallbackQueryHandler(tg_power_mode_cb, pattern=r"^tgnotif:"))

    # R5 strategy config callbacks
    app.add_handler(CallbackQueryHandler(strategy_handler.strategy_callback, pattern=r"^r5cfg:"))

    # Free text — must be last
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _text_router))

    app.add_error_handler(_global_error_handler)
