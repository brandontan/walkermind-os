"""Append-only audit log writer (separate schema, INSERT-only from app)."""
from __future__ import annotations

import json
import logging
from typing import Any, Optional
from uuid import UUID

from .database import get_pool

logger = logging.getLogger(__name__)


async def write(
    *,
    actor_role: str,
    action: str,
    user_id: Optional[UUID] = None,
    payload: Optional[dict[str, Any]] = None,
) -> None:
    """INSERT into audit.log. Never raises — audit failures must not break flows."""
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO audit.log (user_id, actor_role, action, payload) "
                "VALUES ($1, $2, $3, $4::jsonb)",
                user_id, actor_role, action, json.dumps(payload or {}, default=str),
            )
    except Exception as exc:
        logger.error("audit write failed action=%s user=%s err=%s",
                     action, user_id, exc)
