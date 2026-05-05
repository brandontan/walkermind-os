"""Execution router — paper by default, live ONLY when ALL guards pass.

Behavior contract (per R8):
  • If chosen_mode='live' but any of the five activation guards fails →
    audit a 'live_blocked_fallback_paper' event and route to paper.
  • If chosen_mode='live' and the live engine raises BEFORE submitting to
    CLOB (LivePreSubmitError) → safe to fall back to paper.
  • If chosen_mode='live' and the live engine raises AFTER submitting to
    CLOB → DO NOT fall back; propagate so the operator can reconcile.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from uuid import UUID

from ... import audit
from . import fallback
from . import live as live_engine
from . import paper as paper_engine
from .live import LivePostSubmitError, LivePreSubmitError

logger = logging.getLogger(__name__)


async def execute(*, chosen_mode: str, user_id: UUID, telegram_user_id: int,
                  access_tier: int, market_id: str, market_question: str | None,
                  yes_token_id: str | None, no_token_id: str | None,
                  side: str, size_usdc: Decimal, price: float,
                  idempotency_key: str, strategy_type: str,
                  tp_pct: float | None, sl_pct: float | None,
                  trading_mode: str = "paper") -> dict:
    if chosen_mode == "live":
        try:
            live_engine.assert_live_guards(access_tier, trading_mode)
        except Exception as exc:
            logger.warning("router live→paper fallback (guard fail): %s", exc)
            await audit.write(actor_role="bot",
                              action="live_blocked_fallback_paper",
                              user_id=user_id,
                              payload={"market_id": market_id,
                                       "reason": str(exc)})
            return await _paper(
                user_id, telegram_user_id, market_id, market_question,
                side, size_usdc, price, idempotency_key, strategy_type,
                tp_pct, sl_pct,
            )
        try:
            return await live_engine.execute(
                user_id=user_id, telegram_user_id=telegram_user_id,
                access_tier=access_tier, trading_mode=trading_mode,
                market_id=market_id, market_question=market_question,
                yes_token_id=yes_token_id, no_token_id=no_token_id,
                side=side, size_usdc=size_usdc, price=price,
                idempotency_key=idempotency_key, strategy_type=strategy_type,
                tp_pct=tp_pct, sl_pct=sl_pct,
            )
        except LivePostSubmitError:
            # CLOB order is live on-chain — DO NOT paper-duplicate. Re-raise.
            # We DO flip the user's mode to paper so the NEXT signal goes
            # through the paper engine even though this one is reconciled
            # manually by the operator. The in-flight order itself is not
            # touched (the close router still routes to live for the open
            # position the ambiguous submit may have created).
            logger.error("router refusing paper fallback: live order already submitted")
            try:
                await fallback.trigger_for_clob_error(user_id)
            except Exception as fb_exc:  # noqa: BLE001
                logger.error("post-submit fallback trigger failed: %s", fb_exc)
            raise
        except LivePreSubmitError as exc:
            logger.warning("router live→paper fallback (pre-submit fail): %s", exc)
            await audit.write(actor_role="bot",
                              action="live_blocked_fallback_paper",
                              user_id=user_id,
                              payload={"market_id": market_id,
                                       "reason": f"pre_submit:{exc}"})
            # If the pre-submit failure was the runtime live-trading guard
            # going dark (operator flipped ENABLE_LIVE_TRADING off mid-flight),
            # also persist the paper fallback on the user's settings so future
            # signal scans never re-attempt live until /live_checklist passes.
            if "ENABLE_LIVE_TRADING=false" in str(exc):
                try:
                    await fallback.trigger_for_live_guard_unset(user_id)
                except Exception as fb_exc:  # noqa: BLE001
                    logger.error(
                        "live_guard_unset fallback trigger failed: %s", fb_exc,
                    )
            return await _paper(
                user_id, telegram_user_id, market_id, market_question,
                side, size_usdc, price, idempotency_key, strategy_type,
                tp_pct, sl_pct,
            )
    return await _paper(
        user_id, telegram_user_id, market_id, market_question,
        side, size_usdc, price, idempotency_key, strategy_type,
        tp_pct, sl_pct,
    )


async def _paper(user_id, telegram_user_id, market_id, market_question, side,
                 size_usdc, price, idempotency_key, strategy_type, tp_pct, sl_pct):
    return await paper_engine.execute(
        user_id=user_id, telegram_user_id=telegram_user_id,
        market_id=market_id, market_question=market_question,
        side=side, size_usdc=size_usdc, price=price,
        idempotency_key=idempotency_key, strategy_type=strategy_type,
        tp_pct=tp_pct, sl_pct=sl_pct,
    )


async def close(*, position: dict, exit_price: float, exit_reason: str) -> dict:
    """Close uses the engine that opened the position.

    Live close paths intentionally do NOT re-check the open-time guards: an
    existing live exposure must always be unwindable, even if the operator has
    since flipped a guard off or the user switched their mode back to paper.
    """
    if position.get("mode") == "live":
        return await live_engine.close_position(
            position=position, exit_price=exit_price, exit_reason=exit_reason,
        )
    return await paper_engine.close_position(
        position=position, exit_price=exit_price, exit_reason=exit_reason,
    )
