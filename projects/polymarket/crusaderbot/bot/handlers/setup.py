"""Strategy / risk / capital / TP-SL / copy-target setup flow."""
from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ...database import get_pool
from ...users import get_settings_for, update_settings, upsert_user
from ..keyboards import (
    autoredeem_picker, category_picker, mode_picker, risk_picker,
    setup_menu, strategy_card_kb, strategy_picker,
)
from ..tier import Tier, has_tier, tier_block_message
from . import presets as presets_handler

logger = logging.getLogger(__name__)

STRATEGY_DISPLAY_NAMES: dict[str, str] = {
    "signal":            "Signal",
    "value":             "Edge Finder",
    "edge_finder":       "Edge Finder",
    "momentum_reversal": "Momentum Reversal",
    "momentum":          "Momentum Reversal",
    "all":               "All Strategies",
}


async def _ensure_tier2(update: Update) -> tuple[dict | None, bool]:
    if update.effective_user is None:
        return None, False
    user = await upsert_user(update.effective_user.id, update.effective_user.username)
    if not has_tier(user["access_tier"], Tier.ALLOWLISTED):
        msg = tier_block_message(Tier.ALLOWLISTED)
        if update.message:
            await update.message.reply_text(msg)
        elif update.callback_query:
            await update.callback_query.answer(msg, show_alert=True)
        return None, False
    return user, True


_AUTOTRADE_TEXT = (
    "🤖 *Auto-Trade Strategy*\n"
    "──────────────────\n"
    "Pick your trading strategy:\n\n"
    "📡 *Signal*\n"
    "Reacts to market momentum shifts.\n"
    "_Best for: short-term moves._\n\n"
    "🔍 *Edge Finder*\n"
    "Finds underpriced contracts.\n"
    "_Best for: medium-term holds._\n\n"
    "🔄 *Momentum Reversal*\n"
    "Detects overreaction, trades the bounce.\n"
    "_Best for: contrarian plays._\n\n"
    "⚡ *All Strategies*\n"
    "Runs all three in parallel."
)


async def setup_root(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """🤖 Auto-Trade reply-keyboard button → strategy card picker (single render)."""
    user, ok = await _ensure_tier2(update)
    if not ok or update.message is None:
        return
    await update.message.reply_text(
        _AUTOTRADE_TEXT,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=strategy_card_kb(),
    )


async def setup_legacy_root(update: Update,
                            ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Legacy raw-strategy setup menu (pre-Phase 5C)."""
    user, ok = await _ensure_tier2(update)
    if not ok or update.message is None:
        return
    s = await get_settings_for(user["id"])
    text = (
        "*🤖 Setup*\n\n"
        f"Strategy: `{', '.join(STRATEGY_DISPLAY_NAMES.get(t, t) for t in (s['strategy_types'] or []))}`\n"
        f"Risk profile: `{s['risk_profile']}`\n"
        f"Capital alloc: `{float(s['capital_alloc_pct']) * 100:.0f}%`\n"
        f"TP/SL: `{s['tp_pct'] or '—'} / {s['sl_pct'] or '—'}`\n"
        f"Mode: `{s['trading_mode']}`\n"
        f"Auto-redeem: `{s['auto_redeem_mode']}`\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN,
                                    reply_markup=setup_menu())


async def setup_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if q is None:
        return
    await q.answer()
    user, ok = await _ensure_tier2(update)
    if not ok:
        return
    sub = (q.data or "").split(":", 1)[-1]
    s = await get_settings_for(user["id"])

    if sub == "menu":
        await q.message.edit_reply_markup(reply_markup=setup_menu())
        return
    if sub == "strategy":
        # Route to the new strategy card UI.
        await q.message.reply_text(
            _AUTOTRADE_TEXT,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=strategy_card_kb(),
        )
        return
    elif sub == "capital":
        # Remap legacy setup:capital → new settings capital preset flow.
        from ..keyboards.settings import capital_preset_kb as _cap_kb
        from ...wallet.ledger import get_balance as _get_balance
        bal = float(await _get_balance(user["id"]))
        mode = s.get("trading_mode", "paper")
        await q.message.reply_text(
            "💰 *Capital Allocation Per Trade*\n"
            "──────────────────\n"
            f"Balance: ${bal:.2f} ({'Live' if mode == 'live' else 'Paper'})\n\n"
            "⚠️ Max 95% — full allocation forbidden.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=_cap_kb(bal, mode),
        )
    elif sub == "tpsl":
        # Remap legacy setup:tpsl → new settings TP/SL preset flow (step 1).
        from ..keyboards.settings import tp_preset_kb as _tp_kb
        current_tp = float(s["tp_pct"]) if s.get("tp_pct") is not None else None
        current_str = f"+{current_tp * 100:.0f}%" if current_tp is not None else "not set"
        await q.message.reply_text(
            f"📊 *Take Profit*\nCurrent: {current_str}\n\nSelect your take-profit target:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=_tp_kb(current_tp * 100 if current_tp else None),
        )
    elif sub == "risk":
        await q.message.reply_text("Pick risk profile:",
                                   reply_markup=risk_picker(s["risk_profile"]))
    elif sub == "categories":
        await q.message.reply_text("Pick categories:",
                                   reply_markup=category_picker(s["category_filters"]))
    elif sub == "copy":
        ctx.user_data["awaiting"] = "copy_target"
        await q.message.reply_text(
            "Send a Polygon wallet address (0x…) to copy-trade. Send `list` to see "
            "current targets, or `remove 0x…` to remove one.",
            parse_mode=ParseMode.MARKDOWN,
        )
    elif sub == "mode":
        await q.message.reply_text(
            "Pick trading mode. *Paper* is the safe default; *Live* requires all activation guards.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=mode_picker(s["trading_mode"]),
        )
    elif sub == "redeem":
        await q.message.reply_text(
            "Pick auto-redeem mode.\n\n"
            "*Instant* — settle winning markets the moment they resolve "
            "(live trades are gas-spike guarded).\n"
            "*Hourly* — wait for the hourly batch (default).",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=autoredeem_picker(s["auto_redeem_mode"]),
        )


async def set_strategy(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Legacy checkbox strategy toggle — used by presets and /setup_advanced."""
    q = update.callback_query
    if q is None:
        return
    await q.answer()
    user, ok = await _ensure_tier2(update)
    if not ok:
        return
    choice = (q.data or "").split(":", 1)[-1]
    s = await get_settings_for(user["id"])
    cur = list(s["strategy_types"] or [])
    if choice in cur:
        cur.remove(choice)
    else:
        cur.append(choice)
    if not cur:
        cur = ["copy_trade"]
    await update_settings(user["id"], strategy_types=cur)
    await q.message.edit_reply_markup(reply_markup=strategy_picker(cur))


# Internal mapping: user-facing card label → backend strategy name(s).
_CARD_TO_BACKEND: dict[str, list[str]] = {
    "signal":              ["signal"],
    "edge_finder":         ["value"],
    "momentum_reversal":   ["momentum_reversal"],
    "all":                 ["signal", "value", "momentum_reversal"],
}

_CARD_CONFIRM: dict[str, str] = {
    "signal":            "Signal",
    "edge_finder":       "Edge Finder",
    "momentum_reversal": "Momentum Reversal",
    "all":               "All Strategies",
}


async def set_strategy_card(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle strategy:<card> callbacks from the Auto-Trade strategy card menu."""
    q = update.callback_query
    if q is None:
        return
    await q.answer()
    user, ok = await _ensure_tier2(update)
    if not ok:
        return
    card = (q.data or "").split(":", 1)[-1]

    if card == "back":
        from ..keyboards import main_menu
        await q.message.reply_text("Main menu:", reply_markup=main_menu())
        return

    backend = _CARD_TO_BACKEND.get(card)
    if backend is None:
        return

    await update_settings(user["id"], strategy_types=backend)
    label = _CARD_CONFIRM.get(card, card)
    await q.message.reply_text(
        f"✅ Strategy set to *{label}*.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=strategy_card_kb(),
    )


async def set_risk(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if q is None:
        return
    await q.answer()
    user, ok = await _ensure_tier2(update)
    if not ok:
        return
    choice = (q.data or "").split(":", 1)[-1]
    if choice not in ("conservative", "balanced", "aggressive"):
        return
    await update_settings(user["id"], risk_profile=choice)
    await q.message.edit_reply_markup(reply_markup=risk_picker(choice))


async def set_category(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if q is None:
        return
    await q.answer()
    user, ok = await _ensure_tier2(update)
    if not ok:
        return
    choice = (q.data or "").split(":", 1)[-1]
    s = await get_settings_for(user["id"])
    cur = list(s["category_filters"] or [])
    if choice == "all":
        cur = []
    else:
        if choice in cur:
            cur.remove(choice)
        else:
            cur.append(choice)
    await update_settings(user["id"], category_filters=cur)
    await q.message.edit_reply_markup(reply_markup=category_picker(cur))


async def set_mode(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if q is None:
        return
    await q.answer()
    user, ok = await _ensure_tier2(update)
    if not ok:
        return
    choice = (q.data or "").split(":", 1)[-1]
    if choice not in ("paper", "live"):
        return
    if choice == "live":
        # Switching trading_mode to 'live' is itself a live-activation
        # event — for any user with auto_trade_on=true (the common case
        # after a paper run), the very next signal routes real CLOB
        # orders. The checklist + CONFIRM dialog must therefore gate
        # this picker as strictly as the dashboard auto-trade toggle.
        # ``activation.trading_mode_live_pending_confirm`` runs the full
        # 8-gate checklist, refuses the switch with a fix list when any
        # gate fails, and otherwise arms a typed-CONFIRM flow that
        # writes ``trading_mode='live'`` only after the user replies
        # CONFIRM. We do NOT call ``update_settings`` here when the
        # confirmation path is engaged.
        from .activation import trading_mode_live_pending_confirm
        if await trading_mode_live_pending_confirm(update, ctx):
            return
    await update_settings(user["id"], trading_mode=choice)
    await q.message.edit_reply_markup(reply_markup=mode_picker(choice))


async def set_redeem_mode(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if q is None:
        return
    await q.answer()
    user, ok = await _ensure_tier2(update)
    if not ok:
        return
    choice = (q.data or "").split(":", 1)[-1]
    if choice not in ("instant", "hourly"):
        return
    await update_settings(user["id"], auto_redeem_mode=choice)
    await q.message.reply_text(f"Auto-redeem mode set to *{choice}*.",
                               parse_mode=ParseMode.MARKDOWN)


async def text_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    """Returns True if the input was consumed by an awaiting setup prompt."""
    if update.message is None or update.effective_user is None:
        return False
    awaiting = ctx.user_data.get("awaiting") if ctx.user_data else None
    if not awaiting:
        return False
    user = await upsert_user(update.effective_user.id, update.effective_user.username)
    text = (update.message.text or "").strip()

    # Per round-6 review feedback: only clear `awaiting` on success so an
    # invalid value lets the user retry without re-opening the menu.
    try:
        if awaiting == "capital_pct":
            pct = float(text)
            # Cap strictly < 1.0 (max 95%). Full allocation is forbidden by
            # CLAUDE.md hard rule (no full Kelly equivalent).
            if not 1 <= pct <= 95:
                await update.message.reply_text(
                    "❌ capital_alloc_pct must be less than 1.0 (100%). "
                    "Max allowed: 0.95"
                )
                # Keep `awaiting` so the user can retry immediately.
                return True
            capital_alloc = pct / 100.0
            assert 0 < capital_alloc < 1.0, \
                f"capital_alloc_pct {capital_alloc} must be < 1.0"
            await update_settings(user["id"], capital_alloc_pct=capital_alloc)
            await update.message.reply_text(
                f"✅ Capital allocation set to {pct:.0f}%."
            )
        elif awaiting == "copy_target":
            await _handle_copy_target_input(update, user, text)
        else:
            # Unknown awaiting value — could belong to another consumer
            # (e.g. activation's CONFIRM flow). Do NOT pop it, otherwise
            # the next consumer in the dispatcher chain would see no
            # pending state and miss a real reply. Just decline.
            return False
    except Exception as exc:
        logger.warning("setup text input rejected: %s", exc)
        await update.message.reply_text(
            "❌ Couldn't parse that — try again or send /menu to exit."
        )
        # Keep `awaiting` set so the user can retry immediately.
        return True
    ctx.user_data.pop("awaiting", None)
    return True


async def _handle_copy_target_input(update: Update, user: dict, text: str) -> None:
    pool = get_pool()
    if text.lower() == "list":
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT wallet_address, scale_factor, enabled FROM copy_targets "
                "WHERE user_id=$1", user["id"],
            )
        if not rows:
            await update.message.reply_text("No copy targets yet.")
            return
        lines = [f"`{r['wallet_address']}` x{float(r['scale_factor'])} "
                 f"{'✅' if r['enabled'] else '❌'}" for r in rows]
        await update.message.reply_text("\n".join(lines),
                                        parse_mode=ParseMode.MARKDOWN)
        return
    if text.lower().startswith("remove "):
        addr = text.split(" ", 1)[1].strip()
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM copy_targets WHERE user_id=$1 AND wallet_address=$2",
                user["id"], addr,
            )
        await update.message.reply_text(f"Removed {addr}.")
        return
    addr = text
    if not (addr.startswith("0x") and len(addr) == 42):
        await update.message.reply_text("❌ Not a valid 0x address.")
        return
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO copy_targets (user_id, wallet_address) VALUES ($1, $2) "
            "ON CONFLICT (user_id, wallet_address) DO NOTHING",
            user["id"], addr,
        )
    await update.message.reply_text(f"✅ Added copy target `{addr}`",
                                    parse_mode=ParseMode.MARKDOWN)
