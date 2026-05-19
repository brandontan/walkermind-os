"""Regression: get_live_market_price must never return the empty-book
sentinel (exactly 1.0 / 0.0) as a live mark for an open position.

Issue #1182 (WARP-38): a YES position bought at 5.5c showed +927% P&L
because CLOB /price returned 1.0 (no asks on a thin longshot book) and
the old guard ``0.0 <= clob_price <= 1.0`` accepted it. The fix requires
a strictly-interior price; degenerate sentinels fall back to the Gamma
outcomePrices last trade, and an all-invalid lookup returns None so the
caller marks at entry_price (unrealised P&L == 0 / "N/A").
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional
from unittest.mock import AsyncMock, patch

from projects.polymarket.crusaderbot.integrations import polymarket


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


_GAMMA_MARKET = {
    "tokens": [{"token_id": "yes_tok"}, {"token_id": "no_tok"}],
    # Real last-trade price for the longshot — the correct mark.
    "outcomePrices": '["0.055", "0.945"]',
}


def _patches(clob_price: Optional[Any]):
    """Patch cache + HTTP so the first _get_json call returns the Gamma
    market and the second (CLOB /price) returns ``clob_price``.
    """

    async def fake_get_json(url: str, params=None, timeout: float = 5.0):
        if "/price" in url:
            return {"price": clob_price} if clob_price is not None else {}
        return [_GAMMA_MARKET]

    return (
        patch.object(polymarket, "get_cache", AsyncMock(return_value=None)),
        patch.object(polymarket, "set_cache", AsyncMock(return_value=None)),
        patch.object(polymarket, "_get_json", side_effect=fake_get_json),
    )


def test_clob_sentinel_one_falls_back_to_gamma() -> None:
    """CLOB returns 1.0 (empty ask book) -> use Gamma 0.055, not 1.0."""
    p_cache, p_set, p_json = _patches(clob_price="1")
    with p_cache, p_set, p_json:
        price = _run(polymarket.get_live_market_price("0xabc", "yes"))
    assert price == 0.055


def test_clob_sentinel_zero_falls_back_to_gamma() -> None:
    """CLOB returns 0.0 (empty bid book) -> use Gamma fallback."""
    p_cache, p_set, p_json = _patches(clob_price="0")
    with p_cache, p_set, p_json:
        price = _run(polymarket.get_live_market_price("0xabc", "yes"))
    assert price == 0.055


def test_clob_interior_price_accepted() -> None:
    """A real interior CLOB price is still returned as-is."""
    p_cache, p_set, p_json = _patches(clob_price="0.061")
    with p_cache, p_set, p_json:
        price = _run(polymarket.get_live_market_price("0xabc", "yes"))
    assert price == 0.061


def test_gamma_sentinel_returns_none() -> None:
    """CLOB empty AND Gamma outcomePrices == 1.0 -> None (caller marks at
    entry_price; never an inflated 1.0 mark)."""

    async def fake_get_json(url: str, params=None, timeout: float = 5.0):
        if "/price" in url:
            return {"price": "1"}
        return [{
            "tokens": [{"token_id": "yes_tok"}, {"token_id": "no_tok"}],
            "outcomePrices": '["1", "0"]',
        }]

    with patch.object(polymarket, "get_cache", AsyncMock(return_value=None)), \
         patch.object(polymarket, "set_cache", AsyncMock(return_value=None)), \
         patch.object(polymarket, "_get_json", side_effect=fake_get_json):
        price = _run(polymarket.get_live_market_price("0xabc", "yes"))
    assert price is None
