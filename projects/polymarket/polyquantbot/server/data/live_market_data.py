"""Live market data provider for CrusaderBot — guards against stale paper-only pricing.

LiveMarketDataProvider is the interface contract for real market price feeds in
live mode.  It replaces the no-op stub that price_updater() previously used and
enforces that:
  1. In live mode: a real price must be fetched from the CLOB or Gamma API.
  2. Stale data (older than STALE_THRESHOLD_SECONDS) is rejected as unsafe.
  3. In paper mode: a PaperMarketDataProvider (no-op fallback) is used.

This is a NARROW INTEGRATION:
  - The provider interface and validation logic are fully built and tested.
  - The real HTTP implementation (AiohttpClobMarketDataClient) is wired in
    but requires live CLOB credentials; it is not activated by default.
  - price_updater integration hook is in PaperBetaWorker — see run_once().
  - EXECUTION_PATH_VALIDATED is NOT set by this module.

Claim level: NARROW INTEGRATION
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import structlog

log = structlog.get_logger(__name__)

# Stale data threshold — prices older than this are rejected in live mode
STALE_THRESHOLD_SECONDS: float = 60.0


# ── Errors ────────────────────────────────────────────────────────────────────


class StaleMarketDataError(Exception):
    """Raised when live-mode price data is older than STALE_THRESHOLD_SECONDS.

    Attributes:
        token_id:    Token whose price was requested.
        age_seconds: Age of the cached price in seconds.
    """

    def __init__(self, token_id: str, age_seconds: float) -> None:
        self.token_id = token_id
        self.age_seconds = age_seconds
        super().__init__(
            f"Stale market data for token {token_id!r}: "
            f"price is {age_seconds:.1f}s old (max {STALE_THRESHOLD_SECONDS}s)"
        )


class LiveMarketDataUnavailableError(Exception):
    """Raised when live market data cannot be fetched (network error, missing token, etc.)."""


# ── Price result ──────────────────────────────────────────────────────────────


@dataclass
class MarketPrice:
    """Typed price result from a market data provider.

    Attributes:
        token_id:       Polymarket token ID.
        price:          Mid-market price (0.0–1.0).
        bid:            Best bid price (0.0–1.0).
        ask:            Best ask price (0.0–1.0).
        fetched_at_ns:  Unix nanoseconds at fetch time (for staleness check).
        source:         Provider label ("clob_api", "gamma_api", "paper_stub", etc.).
    """

    token_id: str
    price: float
    bid: float
    ask: float
    fetched_at_ns: int
    source: str

    @property
    def age_seconds(self) -> float:
        """Age of this price record in seconds."""
        return (time.time_ns() - self.fetched_at_ns) / 1_000_000_000.0

    def is_stale(self, threshold_seconds: float = STALE_THRESHOLD_SECONDS) -> bool:
        """Return True if the price is older than threshold_seconds."""
        return self.age_seconds > threshold_seconds


# ── Provider protocol ──────────────────────────────────────────────────────────


@runtime_checkable
class MarketDataProvider(Protocol):
    """Protocol for market data providers.

    Both live and paper implementations must satisfy this protocol.
    Live mode requires a real implementation; paper mode may use PaperMarketDataProvider.
    """

    async def get_price(self, token_id: str) -> MarketPrice:
        """Fetch the current market price for a token.

        Args:
            token_id: Polymarket token ID.

        Returns:
            MarketPrice with price, bid, ask, and fetch timestamp.

        Raises:
            LiveMarketDataUnavailableError: Cannot fetch price.
            StaleMarketDataError:           Fetched price exceeds stale threshold (live only).
        """
        ...


# ── Paper stub (no-op, safe only in paper mode) ───────────────────────────────


class PaperMarketDataProvider:
    """No-op market data provider for paper mode.

    Returns a synthetic price based on a configurable default.  This provider
    MUST NOT be used in live mode — see LiveMarketDataGuard.

    Args:
        default_price: Synthetic price to return (default 0.5).
        source_label:  Label injected into MarketPrice.source.
    """

    def __init__(
        self,
        default_price: float = 0.5,
        source_label: str = "paper_stub",
    ) -> None:
        self._default_price = default_price
        self._source_label = source_label

    async def get_price(self, token_id: str) -> MarketPrice:
        log.debug("paper_market_data_provider_price", token_id=token_id, price=self._default_price)
        return MarketPrice(
            token_id=token_id,
            price=self._default_price,
            bid=self._default_price - 0.01,
            ask=self._default_price + 0.01,
            fetched_at_ns=time.time_ns(),
            source=self._source_label,
        )


# ── Live market data guard ────────────────────────────────────────────────────


class LiveMarketDataGuard:
    """Guard that rejects stale or paper-stub prices in live mode.

    Wraps any MarketDataProvider and adds staleness validation.
    In live mode, a price from PaperMarketDataProvider is rejected
    (source == "paper_stub" triggers LiveMarketDataUnavailableError).

    Args:
        provider:           Underlying MarketDataProvider.
        stale_threshold_s:  Staleness threshold in seconds (default STALE_THRESHOLD_SECONDS).
        mode:               "live" or "paper" — controls validation behavior.
    """

    def __init__(
        self,
        provider: MarketDataProvider,
        stale_threshold_s: float = STALE_THRESHOLD_SECONDS,
        mode: str = "paper",
    ) -> None:
        self._provider = provider
        self._stale_threshold_s = stale_threshold_s
        self._mode = mode

    async def get_price(self, token_id: str) -> MarketPrice:
        """Fetch and validate a market price.

        In live mode:
          - Rejects paper_stub source (raises LiveMarketDataUnavailableError).
          - Rejects stale prices (raises StaleMarketDataError).
        In paper mode:
          - Returns price without staleness check.

        Args:
            token_id: Polymarket token ID.

        Returns:
            Validated MarketPrice.

        Raises:
            LiveMarketDataUnavailableError: Paper stub used in live mode.
            StaleMarketDataError:           Price is stale in live mode.
        """
        price = await self._provider.get_price(token_id)

        if self._mode == "live":
            if price.source == "paper_stub":
                log.error(
                    "live_market_data_guard_paper_stub_rejected",
                    token_id=token_id,
                    source=price.source,
                    mode=self._mode,
                )
                raise LiveMarketDataUnavailableError(
                    f"Paper stub price source {price.source!r} rejected in live mode "
                    f"for token {token_id!r} — inject a real MarketDataProvider"
                )
            if price.is_stale(self._stale_threshold_s):
                log.error(
                    "live_market_data_guard_stale_price_rejected",
                    token_id=token_id,
                    age_seconds=price.age_seconds,
                    threshold_seconds=self._stale_threshold_s,
                    source=price.source,
                )
                raise StaleMarketDataError(token_id=token_id, age_seconds=price.age_seconds)

        log.debug(
            "live_market_data_guard_price_ok",
            token_id=token_id,
            price=price.price,
            source=price.source,
            age_seconds=price.age_seconds,
            mode=self._mode,
        )
        return price


# ── Mock CLOB client (for integration tests — no real network) ────────────────


class MockClobMarketDataClient:
    """Deterministic mock market data client for integration tests.

    Returns configurable prices without any network call.  Can simulate
    stale data by setting fetched_at_ns to a past timestamp.

    Args:
        price:         Price to return (default 0.65).
        stale_offset_s: If > 0, sets fetched_at_ns to this many seconds in the past.
        source:        Source label (default "clob_api_mock").
        raise_on_fetch: If set, raises this exception on get_price().
    """

    def __init__(
        self,
        price: float = 0.65,
        stale_offset_s: float = 0.0,
        source: str = "clob_api_mock",
        raise_on_fetch: Exception | None = None,
    ) -> None:
        self._price = price
        self._stale_offset_s = stale_offset_s
        self._source = source
        self._raise_on_fetch = raise_on_fetch
        self.call_count: int = 0

    async def get_price(self, token_id: str) -> MarketPrice:
        self.call_count += 1
        if self._raise_on_fetch is not None:
            raise self._raise_on_fetch
        stale_ns = int(self._stale_offset_s * 1_000_000_000)
        fetched_at = time.time_ns() - stale_ns
        return MarketPrice(
            token_id=token_id,
            price=self._price,
            bid=self._price - 0.01,
            ask=self._price + 0.01,
            fetched_at_ns=fetched_at,
            source=self._source,
        )
