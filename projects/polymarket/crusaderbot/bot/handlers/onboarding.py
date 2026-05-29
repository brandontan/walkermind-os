"""Concierge Onboarding — 8-step interactive wizard for new users.

Flow:
  Step 1  ONBOARD_WELCOME       → brand card + "🚀 Begin Setup"
  Step 2  ONBOARD_HOW_IT_WORKS  → 3-bullet explainer + "Got it →"
  Step 3  ONBOARD_WALLET        → wallet address shown, $1k seeded + "Next →"
  Step 4  ONBOARD_PAPER_CREDIT  → "$1,000 added" confirmation + "Continue →"
  Step 5  ONBOARD_RISK_PROFILE  → Conservative / Balanced / Aggressive
  Step 6  ONBOARD_PRESET_PICK   → 8 strategy presets
  Step 7  ONBOARD_REVIEW        → summary card + "🚀 Start Trading"
  Step 8  [launch → Dashboard]  → apply preset, mark complete, END

Returning users (onboarding_complete=True) skip directly to Dashboard.
"""
from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from ... import audit
from ...domain.preset import get_preset
from ...domain.preset.presets import capital_for_risk_profile
from ...services.referral.referral_service import (
    get_or_create_referral_code,
    parse_ref_param,
    record_referral,
)
from ...users import (
    set_auto_trade,
    set_onboarding_complete,
    set_paused,
    update_settings,
    upsert_user,
)
from ...wallet.ledger import get_balance
from ...wallet.vault import get_wallet
from ..keyboards import main_menu
from ..messages import (
    DIV,
    onboard_how_it_works_text,
    onboard_paper_credit_text,
    onboard_preset_pick_text,
    onboard_review_text,
    onboard_risk_text,
    onboard_wallet_text,
    onboard_welcome_text,
)
from ..roles import is_admin

logger = logging.getLogger(__name__)

# ── ConversationHandler states ────────────────────────────────────────────────
ONBOARD_WELCOME       = 0
ONBOARD_HOW_IT_WORKS  = 1
ONBOARD_WALLET        = 2
ONBOARD_PAPER_CREDIT  = 3
ONBOARD_RISK_PROFILE  = 4
ONBOARD_PRESET_PICK   = 5
ONBOARD_REVIEW        = 6

_PAPER_SEED = 1000.0

_RISK_LABELS = {
    "conservative": "📡 Conservative",
    "balanced":     "⚡ Balanced",
    "aggressive":   "🚀 Aggressive",
}


# ── Step keyboards ────────────────────────────────────────────────────────────

def _welcome_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🚀 Begin Setup", callback_data="onboard:start"),
    ]])


def _how_it_works_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Got it →", callback_data="onboard:how_next"),
    ]])


def _wallet_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Copy Address", callback_data="onboard:copy_address")],
        [InlineKeyboardButton("Next →",          callback_data="onboard:wallet_next")],
    ])


def _paper_credit_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Continue →", callback_data="onboard:paper_credit_next"),
    ]])


def _risk_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📡 Conservative",            callback_data="onboard:risk:conservative")],
        [InlineKeyboardButton("⚡ Balanced  ⭐ Recommended", callback_data="onboard:risk:balanced")],
        [InlineKeyboardButton("🚀 Aggressive",              callback_data="onboard:risk:aggressive")],
    ])


# Onboarding preset roster — single source of truth. Each tuple is
# (label, callback_key, backing_strategy). When the operator toggles the
# backing strategy OFF via /admin, the preset is hidden from new users so
# they cannot pick a no-op preset (signal_scan_job._preset_allows would
# block execution silently otherwise).
_ONBOARD_PRESETS: tuple[tuple[str, str, str], ...] = (
    ("🧹 Close Sweep ⭐", "close_sweep", "late_entry_v3"),
    ("🔒 Safe Close",     "safe_close",  "late_entry_v3"),
    ("🎯 Flip Hunter",    "flip_hunter", "late_entry_v3"),
)


async def _load_disabled_strategies_for_onboarding() -> frozenset[str]:
    """Read the operator's global on/off set; FAIL-SAFE on DB error.

    Mirrors bot.handlers.presets._load_disabled_strategies — a transient blip
    must never silently empty the onboarding picker.
    """
    from ...database import get_pool
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT name FROM strategies WHERE enabled = FALSE"
            )
        return frozenset(str(r["name"]) for r in rows)
    except Exception:
        logger.exception("onboarding_preset_picker_disabled_lookup_failed")
        return frozenset()


def _preset_pick_kb(disabled: frozenset[str] | None = None) -> InlineKeyboardMarkup:
    """Build the onboarding preset picker, hiding presets whose backing
    strategy is globally disabled. ``disabled`` defaults to empty (FAIL-SAFE)
    so the keyboard never silently empties on a DB blip."""
    blocked = disabled or frozenset()
    rows: list[list[InlineKeyboardButton]] = []
    for label, key, strat in _ONBOARD_PRESETS:
        if strat in blocked:
            continue
        rows.append([InlineKeyboardButton(
            label, callback_data=f"onboard:preset:{key}",
        )])
    return InlineKeyboardMarkup(rows)


def _review_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Start Trading",   callback_data="onboard:launch")],
        [InlineKeyboardButton("← Change Risk",      callback_data="onboard:back_risk")],
    ])


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_address(user_id: int) -> str:
    w = await get_wallet(user_id)
    return w["deposit_address"] if w else "(not set)"


async def _seed_paper_wallet(user_id: int) -> None:
    try:
        bal = await get_balance(user_id)
        if float(bal) == 0.0:
            from ...database import get_pool
            pool = get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO wallets (user_id, balance_usdc) VALUES ($1, $2) "
                    "ON CONFLICT (user_id) DO UPDATE SET balance_usdc = "
                    "  CASE WHEN wallets.balance_usdc = 0 "
                    "       THEN $2 ELSE wallets.balance_usdc END",
                    user_id, _PAPER_SEED,
                )
                await conn.execute(
                    "INSERT INTO ledger (user_id, type, amount_usdc, note) "
                    "VALUES ($1, 'deposit', $2, 'Paper wallet — initial $1,000 credit') "
                    "ON CONFLICT DO NOTHING",
                    user_id, _PAPER_SEED,
                )
    except Exception as exc:
        logger.warning("wallet_seed_failed user=%s err=%s", user_id, exc)


# ── Entry ─────────────────────────────────────────────────────────────────────

async def _entry(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_user is None or update.message is None:
        return ConversationHandler.END

    tg_user    = update.effective_user
    start_param = ctx.args[0] if ctx.args else None
    ref_code    = parse_ref_param(start_param)

    user    = await upsert_user(tg_user.id, tg_user.username)
    user_id = user["id"]

    await audit.write(
        actor_role="user", action="start", user_id=user_id,
        payload={"username": tg_user.username, "ref_code": ref_code},
    )

    if ref_code and not user.get("onboarding_complete"):
        try:
            await record_referral(referrer_code=ref_code, referred_user_id=user_id)
        except Exception as exc:
            logger.warning("referral_record_failed ref=%s err=%s", ref_code, exc)

    try:
        await get_or_create_referral_code(user_id)
    except Exception as exc:
        logger.warning("referral_code_create_failed user=%s err=%s", user_id, exc)

    if user.get("onboarding_complete"):
        from .dashboard import dashboard
        await dashboard(update, ctx)
        return ConversationHandler.END

    # Step 1 — Welcome
    await update.message.reply_text(
        onboard_welcome_text(),
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=_welcome_kb(),
    )
    return ONBOARD_WELCOME


# ── Step 1 → 2: How it works ──────────────────────────────────────────────────

async def _start_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if q is None:
        return ONBOARD_WELCOME
    await q.answer()

    await q.edit_message_text(
        onboard_how_it_works_text(),
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=_how_it_works_kb(),
    )
    return ONBOARD_HOW_IT_WORKS


# ── Step 2 → 3: Wallet init ───────────────────────────────────────────────────

async def _how_next_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if q is None or update.effective_user is None:
        return ONBOARD_HOW_IT_WORKS
    await q.answer()

    user    = await upsert_user(q.from_user.id, q.from_user.username)
    user_id = user["id"]

    # Seed paper wallet before showing step 3
    await _seed_paper_wallet(user_id)

    address = await _get_address(user_id)
    ctx.user_data["onboard_address"] = address

    await q.edit_message_text(
        onboard_wallet_text(address),
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=_wallet_kb(),
    )
    return ONBOARD_WALLET


# ── Step 3 copy-address toast (stays in ONBOARD_WALLET) ──────────────────────

async def _copy_address_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if q is None:
        return ONBOARD_WALLET
    address = ctx.user_data.get("onboard_address", "")
    if address and address != "(not set)":
        await q.answer(f"📋 {address}", show_alert=True)
    else:
        await q.answer("Address not available yet.", show_alert=True)
    return ONBOARD_WALLET


# ── Step 3 → 4: Paper credit confirmation ────────────────────────────────────

async def _wallet_next_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if q is None:
        return ONBOARD_WALLET
    await q.answer()

    await q.edit_message_text(
        onboard_paper_credit_text(),
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=_paper_credit_kb(),
    )
    return ONBOARD_PAPER_CREDIT


# ── Step 4 → 5: Risk profile ──────────────────────────────────────────────────

async def _paper_credit_next_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if q is None:
        return ONBOARD_PAPER_CREDIT
    await q.answer()

    await q.edit_message_text(
        onboard_risk_text(),
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=_risk_kb(),
    )
    return ONBOARD_RISK_PROFILE


# ── Step 5 → 6: Preset picker ─────────────────────────────────────────────────

async def _risk_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if q is None:
        return ONBOARD_RISK_PROFILE
    await q.answer()

    risk_profile = (q.data or "").split(":")[-1]
    ctx.user_data["onboard_risk"] = risk_profile

    disabled = await _load_disabled_strategies_for_onboarding()
    await q.edit_message_text(
        onboard_preset_pick_text(),
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=_preset_pick_kb(disabled),
    )
    return ONBOARD_PRESET_PICK


# ── Step 6 → 7: Review ───────────────────────────────────────────────────────

async def _preset_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if q is None:
        return ONBOARD_PRESET_PICK
    await q.answer()

    preset_key   = (q.data or "").split(":", 2)[-1]
    risk_profile = ctx.user_data.get("onboard_risk", "balanced")
    ctx.user_data["onboard_preset"] = preset_key

    p = get_preset(preset_key)
    preset_emoji = p.emoji if p else "🤖"
    preset_name  = p.name  if p else preset_key.replace("_", " ").title()
    risk_label   = _RISK_LABELS.get(risk_profile, risk_profile.title())

    await q.edit_message_text(
        onboard_review_text(risk_label, preset_emoji, preset_name),
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=_review_kb(),
    )
    return ONBOARD_REVIEW


# ── Back from review → risk picker ───────────────────────────────────────────

async def _back_risk_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if q is None:
        return ONBOARD_REVIEW
    await q.answer()

    await q.edit_message_text(
        onboard_risk_text(),
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=_risk_kb(),
    )
    return ONBOARD_RISK_PROFILE


# ── Step 7 → Launch (END) ─────────────────────────────────────────────────────

async def _launch_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if q is None or update.effective_user is None:
        return ConversationHandler.END
    await q.answer()

    user    = await upsert_user(q.from_user.id, q.from_user.username)
    user_id = user["id"]

    risk_profile = ctx.user_data.pop("onboard_risk",   "balanced")
    preset_key   = ctx.user_data.pop("onboard_preset", None)

    # Persist risk profile
    try:
        capital_pct = capital_for_risk_profile(risk_profile)
        await update_settings(
            user_id,
            risk_profile=risk_profile,
            capital_alloc_pct=capital_pct,
        )
    except Exception as exc:
        logger.warning("risk_profile_set_failed user=%s err=%s", user_id, exc)

    # Apply chosen preset
    if preset_key:
        p = get_preset(preset_key)
        if p is not None:
            try:
                capital_pct = capital_for_risk_profile(risk_profile)
                await update_settings(
                    user_id,
                    active_preset=p.key,
                    strategy_types=list(p.strategies),
                    capital_alloc_pct=capital_pct,
                    tp_pct=p.tp_pct,
                    sl_pct=p.sl_pct,
                    max_position_pct=p.max_position_pct,
                )
                logger.info("onboard.preset_applied user=%s preset=%s", user_id, p.key)
            except Exception as exc:
                logger.warning(
                    "onboard.preset_apply_failed user=%s preset=%s err=%s",
                    user_id, preset_key, exc,
                )

    # Activate scanner
    try:
        await set_auto_trade(user_id, True)
        await set_paused(user_id, False)
    except Exception as exc:
        logger.error("onboard.auto_trade_activate_failed user=%s err=%s", user_id, exc)

    try:
        await set_onboarding_complete(user_id)
    except Exception as exc:
        logger.error("onboard.complete_flag_failed user=%s err=%s", user_id, exc)
    ctx.user_data.pop("onboard_address", None)

    from .dashboard import show_dashboard_for_cb
    await show_dashboard_for_cb(update, ctx)
    return ConversationHandler.END


# ── Menu-tap fallback ─────────────────────────────────────────────────────────

async def _menu_tap_fallback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message:
        from .dashboard import dashboard
        await dashboard(update, ctx)
    return ConversationHandler.END


# ── Standalone menu / help handlers ──────────────────────────────────────────

async def menu_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    await update.message.reply_text(
        "Choose an option:",
        reply_markup=main_menu(),
    )


async def view_dashboard_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    from .dashboard import dashboard
    q = update.callback_query
    if q:
        await q.answer()
    await dashboard(update, ctx)


async def onboard_settings_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    from .settings import settings_hub_root
    q = update.callback_query
    if q:
        await q.answer()
    await settings_hub_root(update, ctx)


async def help_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    await update.message.reply_text(
        "*📖 CrusaderBot Help*\n\n"
        "Use the menu below to navigate:\n"
        "📊 Dashboard   — account overview and status\n"
        "🤖 Auto\\-Trade  — configure your trading strategy\n"
        "💼 Portfolio   — view balance and open positions\n"
        "📈 My Trades   — open positions and trade history\n"
        "⚙️ Settings    — risk, mode, wallet, notifications\n"
        "🚨 Emergency   — pause or lock trading immediately\n\n"
        "Type /start to re\\-run setup at any time\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🏠 Home", callback_data="dashboard:main"),
        ]]),
    )


# ── ConversationHandler builder ───────────────────────────────────────────────

def build_onboard_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("start", _entry)],
        states={
            ONBOARD_WELCOME: [
                CallbackQueryHandler(_start_cb, pattern=r"^onboard:start$"),
            ],
            ONBOARD_HOW_IT_WORKS: [
                CallbackQueryHandler(_how_next_cb, pattern=r"^onboard:how_next$"),
            ],
            ONBOARD_WALLET: [
                CallbackQueryHandler(_copy_address_cb, pattern=r"^onboard:copy_address$"),
                CallbackQueryHandler(_wallet_next_cb,  pattern=r"^onboard:wallet_next$"),
            ],
            ONBOARD_PAPER_CREDIT: [
                CallbackQueryHandler(_paper_credit_next_cb, pattern=r"^onboard:paper_credit_next$"),
            ],
            ONBOARD_RISK_PROFILE: [
                CallbackQueryHandler(_risk_cb, pattern=r"^onboard:risk:"),
            ],
            ONBOARD_PRESET_PICK: [
                CallbackQueryHandler(_preset_cb, pattern=r"^onboard:preset:"),
            ],
            ONBOARD_REVIEW: [
                CallbackQueryHandler(_launch_cb,    pattern=r"^onboard:launch$"),
                CallbackQueryHandler(_back_risk_cb, pattern=r"^onboard:back_risk$"),
            ],
        },
        fallbacks=[
            CommandHandler("start", _entry),
            MessageHandler(filters.TEXT & ~filters.COMMAND, _menu_tap_fallback),
        ],
        per_message=False,
        allow_reentry=True,
        name="concierge_onboarding",
    )
