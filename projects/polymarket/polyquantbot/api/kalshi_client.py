"""Kalshi read-only REST client.

Fetches market listings and recent trades from the Kalshi REST API and
normalises them into a common format compatible with the rest of the
polyquantbot stack.

Normalisation::

    prices   — always in 0–1 range (Kalshi uses cents 0–100, divided by 100).
    timestamps — always ``float`` Unix epoch seconds (UTC).
    outcomes   — ``"YES"`` | ``"NO"`` (mapped from Kalshi ``"yes"`` / ``"no"``).

This module is **READ-ONLY**.  No order placement methods are provided.

Environment variables::

    KALSHI_API_BASE_URL  — default ``https://trading-api.kalshi.com/trade-api/v2``
    KALSHI_API_KEY       — optional auth header (public endpoints are open).

Usage::

    client = KalshiClient.from_env()
    markets = await client.get_markets(limit=50)
    trades  = await client.get_trades(ticker="PRES-2024-REP")
    await client.close()

Retry policy::

    Up to 3 attempts with exponential back-off (1 s, 2 s, 4 s).
    Each attempt times out after 5 s.
    On total failure returns an empty list and logs the error.
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Optional

import structlog

log = structlog.get_logger()

# ── Constants ──────────────────────────────────────────────────────────────────

_DEFAULT_BASE_URL = "https://trading-api.kalshi.com/trade-api/v2"
_REQUEST_TIMEOUT_S: float = 5.0
_MAX_RETRIES: int = 3
_RETRY_BASE_S: float = 1.0


# ── Normalisation helpers ─────────────────────────────────────────────────────


def _cents_to_probability(cents: Any) -> float:
    """Convert Kalshi price in cents (0–100) to probability (0–1).

    Args:
        cents: Raw Kalshi price value.

    Returns:
        Float in [0, 1].  Clamps out-of-range inputs.
    """
    try:
        val = float(cents) / 100.0
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(val, 1.0))


def _normalise_timestamp(raw: Any) -> float:
    """Convert Kalshi timestamp string / number to Unix epoch float.

    Kalshi returns RFC-3339 strings like ``"2024-11-05T18:00:00Z"``.
    Fallback to current time on parse error.

    Args:
        raw: Raw timestamp from Kalshi API.

    Returns:
        Unix epoch seconds as float.
    """
    import datetime

    if raw is None:
        return time.time()

    if isinstance(raw, (int, float)):
        return float(raw)

    try:
        dt = datetime.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt.timestamp()
    except (ValueError, AttributeError):
        log.warning("kalshi_client_bad_timestamp", raw=raw)
        return time.time()


def _map_outcome(raw: Any) -> str:
    """Map Kalshi outcome string to canonical ``"YES"`` / ``"NO"``.

    Args:
        raw: Kalshi side string (e.g. ``"yes"``, ``"no"``, ``"YES"``).

    Returns:
        ``"YES"`` or ``"NO"``.  Defaults to ``"YES"`` for unrecognised values.
    """
    if str(raw).lower() == "no":
        return "NO"
    return "YES"


# ── KalshiClient ─────────────────────────────────────────────────────────────


class KalshiClient:
    """Read-only Kalshi REST API client with retry and normalisation.

    All returned dicts use the normalised schema described in the module
    docstring.  No mutation of exchange state is possible via this client.
    """

    def __init__(
        self,
        base_url: str = _DEFAULT_BASE_URL,
        api_key: Optional[str] = None,
        request_timeout_s: float = _REQUEST_TIMEOUT_S,
        max_retries: int = _MAX_RETRIES,
    ) -> None:
        """Initialise the Kalshi client.

        Args:
            base_url: API root URL.
            api_key: Optional API key (passed as ``Authorization`` header).
            request_timeout_s: Per-request timeout in seconds.
            max_retries: Maximum number of retry attempts per call.
        """
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout_s = request_timeout_s
        self._max_retries = max_retries
        self._session: Optional[Any] = None  # aiohttp.ClientSession

        log.info(
            "kalshi_client_initialized",
            base_url=self._base_url,
            request_timeout_s=request_timeout_s,
            max_retries=max_retries,
            auth_enabled=api_key is not None,
        )

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_env(cls) -> "KalshiClient":
        """Build from environment variables.

        Reads ``KALSHI_API_BASE_URL`` and ``KALSHI_API_KEY``.

        Returns:
            Configured KalshiClient.
        """
        base_url = os.environ.get("KALSHI_API_BASE_URL", _DEFAULT_BASE_URL)
        api_key = os.environ.get("KALSHI_API_KEY") or None
        return cls(base_url=base_url, api_key=api_key)

    # ── Session lifecycle ─────────────────────────────────────────────────────

    async def _get_session(self) -> Any:
        """Return (or create) the underlying aiohttp session.

        Lazy initialisation so the client can be constructed outside an
        async context.
        """
        if self._session is None or self._session.closed:
            try:
                import aiohttp  # type: ignore[import]

                headers: dict[str, str] = {"Accept": "application/json"}
                if self._api_key:
                    headers["Authorization"] = f"Bearer {self._api_key}"

                self._session = aiohttp.ClientSession(headers=headers)
            except ImportError:
                log.error("kalshi_client_aiohttp_not_installed")
                raise RuntimeError(
                    "aiohttp is required for KalshiClient. "
                    "Install with: pip install aiohttp"
                )
        return self._session

    async def close(self) -> None:
        """Close the underlying HTTP session."""
        if self._session is not None and not self._session.closed:
            await self._session.close()
            log.info("kalshi_client_session_closed")

    # ── Internal request helper ───────────────────────────────────────────────

    async def _get(self, path: str, params: Optional[dict] = None) -> Any:
        """Perform a GET request with retry + timeout.

        Args:
            path: API path (appended to base_url).
            params: Optional query parameters.

        Returns:
            Parsed JSON response (dict or list).  Returns ``None`` on total
            failure so callers can fall back gracefully.
        """
        url = f"{self._base_url}{path}"
        last_exc: Optional[Exception] = None

        for attempt in range(1, self._max_retries + 1):
            try:
                session = await self._get_session()
                async with session.get(
                    url,
                    params=params,
                    timeout=self._timeout_s,
                ) as resp:
                    resp.raise_for_status()
                    return await resp.json()
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                wait_s = _RETRY_BASE_S * (2 ** (attempt - 1))
                log.warning(
                    "kalshi_client_request_failed",
                    url=url,
                    attempt=attempt,
                    max_retries=self._max_retries,
                    error=str(exc),
                    retry_in_s=wait_s if attempt < self._max_retries else None,
                )
                if attempt < self._max_retries:
                    await asyncio.sleep(wait_s)

        log.error(
            "kalshi_client_all_retries_exhausted",
            url=url,
            error=str(last_exc),
        )
        return None

    # ── Public API ────────────────────────────────────────────────────────────

    async def get_markets(
        self,
        status: str = "open",
        limit: int = 100,
    ) -> list[dict]:
        """Fetch and normalise open Kalshi markets.

        Args:
            status: Market status filter (``"open"``, ``"closed"``, etc.).
            limit: Maximum number of markets to return.

        Returns:
            List of normalised market dicts, empty list on failure::

                {
                    "ticker":       str,     # Kalshi market ticker
                    "title":        str,     # human-readable question
                    "yes_price":    float,   # normalised 0–1 probability
                    "no_price":     float,   # normalised 0–1 probability
                    "volume":       float,   # total volume (USD)
                    "open_interest":float,   # open interest (USD)
                    "close_time":   float,   # Unix epoch resolution time
                    "status":       str,     # raw status string
                    "_source":      "kalshi"
                }
        """
        data = await self._get(
            "/markets",
            params={"status": status, "limit": limit},
        )

        if data is None:
            return []

        raw_markets = data.get("markets", data) if isinstance(data, dict) else data
        if not isinstance(raw_markets, list):
            log.warning("kalshi_client_unexpected_markets_response", data_type=type(data).__name__)
            return []

        normalised: list[dict] = []
        for raw in raw_markets:
            try:
                normalised.append(self._normalise_market(raw))
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "kalshi_client_market_normalise_error",
                    error=str(exc),
                    ticker=raw.get("ticker", "unknown"),
                )
        return normalised

    async def get_trades(
        self,
        ticker: str,
        limit: int = 100,
    ) -> list[dict]:
        """Fetch and normalise recent trades for a Kalshi market.

        Args:
            ticker: Kalshi market ticker (e.g. ``"PRES-2024-REP"``).
            limit: Maximum number of trades to return.

        Returns:
            List of normalised trade dicts, empty list on failure::

                {
                    "trade_id":   str,
                    "ticker":     str,
                    "side":       "YES" | "NO",
                    "price":      float,   # normalised 0–1
                    "size":       float,   # contracts
                    "timestamp":  float,   # Unix epoch seconds
                    "_source":    "kalshi"
                }
        """
        data = await self._get(
            f"/markets/{ticker}/trades",
            params={"limit": limit},
        )

        if data is None:
            return []

        raw_trades = data.get("trades", data) if isinstance(data, dict) else data
        if not isinstance(raw_trades, list):
            log.warning(
                "kalshi_client_unexpected_trades_response",
                ticker=ticker,
                data_type=type(data).__name__,
            )
            return []

        normalised: list[dict] = []
        for raw in raw_trades:
            try:
                normalised.append(self._normalise_trade(raw, ticker))
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "kalshi_client_trade_normalise_error",
                    ticker=ticker,
                    error=str(exc),
                )
        return normalised

    # ── Normalisation ─────────────────────────────────────────────────────────

    def _normalise_market(self, raw: dict) -> dict:
        """Normalise a raw Kalshi market dict.

        Args:
            raw: Raw market dict from the Kalshi API.

        Returns:
            Normalised market dict (see :meth:`get_markets` docstring).
        """
        yes_price = _cents_to_probability(
            raw.get("yes_ask") or raw.get("yes_bid") or raw.get("last_price", 50)
        )
        no_price = _cents_to_probability(
            raw.get("no_ask") or raw.get("no_bid") or (100 - (yes_price * 100))
        )

        return {
            "ticker": str(raw.get("ticker", "")),
            "title": str(raw.get("title", raw.get("question", ""))),
            "yes_price": round(yes_price, 6),
            "no_price": round(no_price, 6),
            "volume": float(raw.get("volume", 0) or 0),
            "open_interest": float(raw.get("open_interest", 0) or 0),
            "close_time": _normalise_timestamp(raw.get("close_time") or raw.get("expiration_time")),
            "status": str(raw.get("status", "unknown")),
            "_source": "kalshi",
        }

    def _normalise_trade(self, raw: dict, ticker: str) -> dict:
        """Normalise a raw Kalshi trade dict.

        Args:
            raw: Raw trade dict from the Kalshi API.
            ticker: Market ticker (used as fallback if not in raw).

        Returns:
            Normalised trade dict (see :meth:`get_trades` docstring).
        """
        return {
            "trade_id": str(raw.get("trade_id", raw.get("id", ""))),
            "ticker": str(raw.get("ticker", ticker)),
            "side": _map_outcome(raw.get("taker_side", raw.get("side", "yes"))),
            "price": _cents_to_probability(raw.get("yes_price") or raw.get("price", 50)),
            "size": float(raw.get("count", raw.get("size", 0)) or 0),
            "timestamp": _normalise_timestamp(raw.get("created_time") or raw.get("timestamp")),
            "_source": "kalshi",
        }
