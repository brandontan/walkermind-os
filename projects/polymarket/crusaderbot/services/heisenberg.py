"""Heisenberg / Falcon API client — thin async wrapper for parameterized retrieval.

Agents used by this project:
  574 — Polymarket Markets (market discovery)
  568 — Polymarket Candlesticks (price action)
  575 — Polymarket Market Insights (liquidity screening)
  585 — Social Pulse (sentiment signals)
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_BASE_URL = "https://narrative.agent.heisenberg.so"
_ENDPOINT = "/api/v2/semantic/retrieve/parameterized"
_TIMEOUT = 30.0


async def retrieve(
    agent_id: int,
    params: dict[str, Any],
    limit: int = 50,
) -> list[dict]:
    """POST to the parameterized-retrieval endpoint and return data.results.

    Returns [] when HEISENBERG_API_TOKEN is unset (caller handles the skip).
    Raises httpx.HTTPStatusError on non-2xx responses.
    """
    token = os.getenv("HEISENBERG_API_TOKEN", "")
    if not token:
        return []

    body: dict[str, Any] = {
        "agent_id": agent_id,
        "params": params,
        "pagination": {"limit": limit, "offset": 0},
        "formatter_config": {"format_type": "raw"},
    }
    logger.debug(
        "heisenberg.retrieve agent_id=%d param_keys=%s limit=%d",
        agent_id, sorted(params.keys()), limit,
    )
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{_BASE_URL}{_ENDPOINT}",
            json=body,
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        payload = resp.json()

    return payload.get("data", {}).get("results", []) or []


__all__ = ["retrieve"]
