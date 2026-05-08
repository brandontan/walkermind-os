"""MarketDataClient — unauthenticated CLOB read endpoints.

Polymarket exposes orderbook, midpoint, spread, and price endpoints
without auth. This client wraps them with the same retry posture as
``ClobAdapter`` (transient errors retried; HTTP errors surfaced) but
without any signing. It is safe to use in CI without credentials.

Kept separate from ``ClobAdapter`` on purpose: the adapter is auth-only
(every method signs); the market-data client never signs and never needs
the L1 private key. Mixing them would force every market-data caller to
provision trading credentials.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .exceptions import ClobAPIError

logger = logging.getLogger(__name__)

DEFAULT_HOST = "https://clob.polymarket.com"
DEFAULT_TIMEOUT = 5.0


class MarketDataClient:
    """Unauthenticated read client for CLOB market data.

    Caller-supplied transport lets tests inject ``httpx.MockTransport``;
    production code constructs without arguments and gets a real client.
    """

    def __init__(
        self,
        *,
        host: str = DEFAULT_HOST,
        timeout: float = DEFAULT_TIMEOUT,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self._host = host.rstrip("/")
        self._http = httpx.AsyncClient(
            base_url=self._host,
            timeout=timeout,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "MarketDataClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    # ----- read endpoints -------------------------------------------

    async def get_orderbook(self, token_id: str) -> dict:
        """``GET /book?token_id=X`` — current orderbook (bids + asks)."""
        return await self._get("/book", params={"token_id": token_id})

    async def get_midpoint(self, token_id: str) -> dict:
        return await self._get("/midpoint", params={"token_id": token_id})

    async def get_spread(self, token_id: str) -> dict:
        return await self._get("/spread", params={"token_id": token_id})

    async def get_price(self, token_id: str, *, side: str = "BUY") -> dict:
        return await self._get(
            "/price",
            params={"token_id": token_id, "side": side.upper()},
        )

    async def get_market(self, condition_id: str) -> dict:
        """``GET /markets/{condition_id}`` — single market by condition id.

        Distinct from the Gamma ``/markets/{market_id}`` endpoint; this
        one returns the CLOB-side view (tokens, tick size, neg_risk flag)
        which the order-builder needs.
        """
        return await self._get(f"/markets/{condition_id}")

    async def get_markets(
        self,
        *,
        next_cursor: Optional[str] = None,
    ) -> dict:
        """``GET /markets`` — paginated list. Returns the raw response so
        callers can chase ``next_cursor`` themselves; we don't auto-page
        because callers usually want only the first slice.
        """
        params: dict[str, Any] = {}
        if next_cursor:
            params["next_cursor"] = next_cursor
        return await self._get("/markets", params=params)

    async def get_tick_size(self, token_id: str) -> str:
        """Convenience wrapper. Returns the tick size as a string ("0.01"
        / "0.001" / etc.) so callers feed it back to the order builder
        unchanged.
        """
        data = await self._get(
            "/tick-size", params={"token_id": token_id}
        )
        # CLOB returns ``{"minimum_tick_size": "0.01"}`` — surface the
        # value directly so callers don't reach into the dict.
        return str(data.get("minimum_tick_size", ""))

    async def get_neg_risk(self, token_id: str) -> bool:
        """Whether the market is a neg-risk market — affects which
        Exchange contract the order builder must target.
        """
        data = await self._get(
            "/neg-risk", params={"token_id": token_id}
        )
        return bool(data.get("neg_risk", False))

    # ----- internals ------------------------------------------------

    async def _get(
        self,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
    ) -> dict:
        async for attempt in AsyncRetrying(
            reraise=True,
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=8),
            retry=retry_if_exception_type(
                (httpx.HTTPError, httpx.TimeoutException)
            ),
        ):
            with attempt:
                resp = await self._http.get(path, params=params)
                if 400 <= resp.status_code < 500:
                    raise ClobAPIError(
                        status_code=resp.status_code,
                        path=path,
                        body=resp.text or "",
                    )
                resp.raise_for_status()
                if not resp.text:
                    return {}
                return resp.json()
        raise RuntimeError("MarketDataClient._get: unreachable")  # pragma: no cover
