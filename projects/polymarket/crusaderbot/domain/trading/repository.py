"""Read-only and paper-close DB queries for the My Trades view (Phase 5I).

Surfaces:
  get_open_positions       — open positions for a user, most-recent first
  get_open_position_for_user — single open position with ownership check
  get_recent_activity      — last N closed positions with realized PnL
  get_activity_page        — paginated closed positions + total count

No writes beyond what paper.close_position already provides — callers
that need to close a paper position should call
``domain.execution.paper.close_position`` directly.
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from ...database import get_pool


async def get_open_positions(user_id: UUID) -> list[dict]:
    """Return open positions for *user_id*, ordered newest first (max 25)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT p.id, p.market_id, p.side, p.size_usdc, p.entry_price,
                   p.mode, p.opened_at, m.question,
                   m.yes_token_id, m.no_token_id
              FROM positions p
              LEFT JOIN markets m ON m.id = p.market_id
             WHERE p.user_id = $1 AND p.status = 'open'
             ORDER BY p.opened_at DESC
             LIMIT 25
            """,
            user_id,
        )
    return [dict(r) for r in rows]


async def get_open_position_for_user(
    user_id: UUID, position_id: UUID
) -> Optional[dict]:
    """Fetch a single open position verified to belong to *user_id*."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT p.id, p.market_id, p.side, p.size_usdc, p.entry_price,
                   p.mode, p.user_id, m.question,
                   m.yes_token_id, m.no_token_id
              FROM positions p
              LEFT JOIN markets m ON m.id = p.market_id
             WHERE p.id = $1 AND p.user_id = $2 AND p.status = 'open'
            """,
            position_id,
            user_id,
        )
    return dict(row) if row else None


async def get_recent_activity(user_id: UUID, limit: int = 5) -> list[dict]:
    """Return the last *limit* closed positions with realized PnL."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT p.id, p.market_id, p.side, p.size_usdc, p.pnl_usdc,
                   p.closed_at, m.question
              FROM positions p
              LEFT JOIN markets m ON m.id = p.market_id
             WHERE p.user_id = $1
               AND p.status = 'closed'
               AND p.pnl_usdc IS NOT NULL
             ORDER BY p.closed_at DESC
             LIMIT $2
            """,
            user_id,
            limit,
        )
    return [dict(r) for r in rows]


async def get_activity_page(
    user_id: UUID, page: int, per_page: int = 10
) -> tuple[list[dict], int]:
    """Return one page of closed positions and the total count.

    *page* is zero-based.  Returns ``(rows, total)``.
    """
    pool = get_pool()
    offset = page * per_page
    async with pool.acquire() as conn:
        total: int = await conn.fetchval(
            """
            SELECT COUNT(*)
              FROM positions
             WHERE user_id = $1
               AND status = 'closed'
               AND pnl_usdc IS NOT NULL
            """,
            user_id,
        )
        rows = await conn.fetch(
            """
            SELECT p.id, p.market_id, p.side, p.size_usdc, p.pnl_usdc,
                   p.closed_at, m.question
              FROM positions p
              LEFT JOIN markets m ON m.id = p.market_id
             WHERE p.user_id = $1
               AND p.status = 'closed'
               AND p.pnl_usdc IS NOT NULL
             ORDER BY p.closed_at DESC
             LIMIT $2 OFFSET $3
            """,
            user_id,
            per_page,
            offset,
        )
    return [dict(r) for r in rows], int(total)
