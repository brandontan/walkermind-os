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
    setup_menu, strategy_picker,
)
from ..tier import Tier, has_tier, tier_block_message

logger = logging.getLogger(__name__)


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


async def setup_root(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user, ok = await _ensure_tier2(update)
    if not ok or update.message is None:
        return
    s = await get_settings_for(user["id"])
    text = (
        "*🤖 Setup*\n\n"
        f"Strategy: `{', '.join(s['strategy_types'])}`\n"
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
        await q.message.reply_text("Pick strategies:",
                                   reply_markup=strategy_picker(s["strategy_types"]))
    elif sub == "risk":
        await q.message.reply_text("Pick risk profile:",
                                   reply_markup=risk_picker(s["risk_profile"]))
    elif sub == "categories":
        await q.message.reply_text("Pick categories:",
                                   reply_markup=category_picker(s["category_filters"]))
    elif sub == "capital":
        ctx.user_data["awaiting"] = "capital_pct"
        await q.message.reply_text(
            "Enter capital allocation percentage (1-95). Example: `50` = use up to "
            "50% of balance per trade. Max 95% — full allocation is forbidden. "
            "Send the number now.",
            parse_mode=ParseMode.MARKDOWN,
        )
    elif sub == "tpsl":
        ctx.user_data["awaiting"] = "tpsl"
        await q.message.reply_text(
            "Enter `TP SL` as two percentages separated by a space. Example: `15 8` "
            "= take profit at +15%, stop loss at -8%. Send `skip` to clear.",
            parse_mode=ParseMode.MARKDOWN,
        )
    elif sub == "copy":
        ctx.user_data["awaiting"] = "copy_target"
        await q.message.reply_text(
            "Send a Polygon wallet address (0x…) to copy-trade. Send `list` to see "
            "current targets, or `remove 0x…` to remove one.",
            parse_mode=ParseMode.MARKDOWN,
        )
    elif sub == "mode":
        await q.message.reply_text(
            "Pick trading mode. *Paper* is the safe default; *Live* requires Tier 4 "
            "+ all activation guards.",
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
        elif awaiting == "tpsl":
            if text.lower() == "skip":
                await update_settings(user["id"], tp_pct=None, sl_pct=None)
                await update.message.reply_text("✅ TP / SL cleared.")
            else:
                tp_s, sl_s = text.split()
                tp = float(tp_s) / 100.0
                sl = float(sl_s) / 100.0
                await update_settings(user["id"], tp_pct=tp, sl_pct=sl)
                await update.message.reply_text(
                    f"✅ TP set to +{tp*100:.1f}%, SL set to -{sl*100:.1f}%."
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
