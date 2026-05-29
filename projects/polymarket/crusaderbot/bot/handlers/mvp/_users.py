"""Shared user-data helpers for MVP handlers.

Wraps the existing project user/wallet accessors so MVP handlers can stay
provider-agnostic. Every read is defensive — failures return zeros / Nones
so the UX always renders.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

log = logging.getLogger(__name__)


async def fetch_user(telegram_user_id: int, username: Optional[str] = None) -> Optional[dict]:
    """Return the canonical user dict (upserts on first sight)."""
    try:
        from ....users import upsert_user  # type: ignore
        return await upsert_user(telegram_user_id, username)
    except Exception as exc:  # noqa: BLE001 — defensive read for UX layer
        log.debug("upsert_user failed: %s", exc)
        try:
            from ....users import get_user_by_telegram_id  # type: ignore
            return await get_user_by_telegram_id(telegram_user_id)
        except Exception as exc2:  # noqa: BLE001
            log.debug("get_user_by_telegram_id failed: %s", exc2)
            return None


async def fetch_settings(user_uuid) -> dict:
    """Read user_settings columns (active_preset, risk_profile, etc.)."""
    out: dict = {"active_preset": None, "risk_profile": "balanced", "trading_mode": "paper"}
    try:
        from ....database import get_pool  # type: ignore
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT active_preset, risk_profile, trading_mode FROM user_settings WHERE user_id=$1",
                user_uuid,
            )
            if row is not None:
                out["active_preset"] = row["active_preset"]
                out["risk_profile"] = row["risk_profile"] or "balanced"
                out["trading_mode"] = row["trading_mode"] or "paper"
    except Exception as exc:  # noqa: BLE001
        log.debug("user_settings read failed: %s", exc)
    return out


async def fetch_balance(user_uuid) -> float:
    try:
        from ....wallet.ledger import get_balance  # type: ignore
        return float(await get_balance(user_uuid) or 0)
    except Exception as exc:  # noqa: BLE001
        log.debug("get_balance failed: %s", exc)
        return 0.0


async def fetch_daily_pnl(user_uuid) -> float:
    try:
        from ....wallet.ledger import daily_pnl  # type: ignore
        return float(await daily_pnl(user_uuid) or 0)
    except Exception as exc:  # noqa: BLE001
        log.debug("daily_pnl failed: %s", exc)
        return 0.0


async def fetch_open_position_count(user_uuid) -> int:
    try:
        from ....database import get_pool  # type: ignore
        pool = get_pool()
        async with pool.acquire() as conn:
            n = await conn.fetchval(
                "SELECT COUNT(*) FROM positions WHERE user_id=$1 AND status IN ('open','pending_settlement')",
                user_uuid,
            )
            return int(n or 0)
    except Exception as exc:  # noqa: BLE001
        log.debug("open position count failed: %s", exc)
        return 0


async def fetch_today_trade_count(user_uuid) -> int:
    try:
        from ....database import get_pool  # type: ignore
        pool = get_pool()
        async with pool.acquire() as conn:
            n = await conn.fetchval(
                """SELECT COUNT(*) FROM positions
                   WHERE user_id=$1
                     AND opened_at >= NOW() - INTERVAL '24 hours'""",
                user_uuid,
            )
            return int(n or 0)
    except Exception as exc:  # noqa: BLE001
        log.debug("today_trade_count failed: %s", exc)
        return 0


async def fetch_open_positions(user_uuid, limit: int = 8) -> list[dict]:
    try:
        from ....database import get_pool  # type: ignore
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT p.id, p.side, p.entry_price, p.size_usdc,
                       m.question AS market_title, m.id AS market_id
                FROM positions p
                LEFT JOIN markets m ON m.id = p.market_id
                WHERE p.user_id=$1 AND p.status='open'
                ORDER BY p.opened_at DESC NULLS LAST
                LIMIT $2
                """,
                user_uuid, limit,
            )
            return [dict(r) for r in rows]
    except Exception as exc:  # noqa: BLE001
        log.debug("open positions fetch failed: %s", exc)
        return []


async def set_auto_trade(user_uuid, on: bool) -> None:
    try:
        from ....users import set_auto_trade as _set  # type: ignore
        await _set(user_uuid, on)
    except Exception as exc:  # noqa: BLE001
        log.debug("set_auto_trade failed: %s", exc)


async def set_paused(user_uuid, paused: bool) -> None:
    try:
        from ....users import set_paused as _set  # type: ignore
        await _set(user_uuid, paused)
    except Exception as exc:  # noqa: BLE001
        log.debug("set_paused failed: %s", exc)
