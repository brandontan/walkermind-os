"""Polymarket CLOB adapter (Phase 4A + Phase 4E resilience).

This package introduces a thin REST adapter against
``https://clob.polymarket.com`` that signs requests directly
(EIP-712 for L1, HMAC-SHA256 for L2, optional builder headers)
without going through the ``py-clob-client`` SDK.

It is wired in through a factory (``get_clob_client``) that returns either
``MockClobClient`` (default -- paper safe) or the real ``ClobAdapter``
based on the ``USE_REAL_CLOB`` setting.

Activation contract:
    USE_REAL_CLOB=False -> MockClobClient (no network)
    USE_REAL_CLOB=True  -> ClobAdapter (still gated by the runtime
                           activation guards in domain.execution.live)

The factory NEVER raises on missing credentials when USE_REAL_CLOB=False --
that branch is the paper-safe default and must remain reachable in CI
without any Polymarket secrets.

Phase 4E adds two singletons -- ``CircuitBreaker`` and ``RateLimiter`` --
that survive across per-call adapter construction. Live execution builds
a fresh adapter for every order, so per-instance breaker state would
never trip; the singletons fix that without leaking the limiter into
test fixtures (``reset_clob_resilience()`` clears them between tests).
"""
from __future__ import annotations

import logging
from typing import Optional, Protocol, runtime_checkable

from ...config import Settings, get_settings
from .adapter import ClobAdapter
from .auth import (
    ClobAuthSigner,
    HMACSigner,
    L1Headers,
    L2Headers,
    BuilderHeaders,
    build_builder_headers,
    build_hmac_signature,
    build_l1_headers,
    build_l2_headers,
)
from .circuit_breaker import CircuitBreaker
from .exceptions import (
    ClobAPIError,
    ClobAuthError,
    ClobCircuitOpenError,
    ClobConfigError,
    ClobError,
    ClobMaxRetriesError,
    ClobNetworkError,
    ClobRateLimitError,
    ClobServerError,
    ClobTimeoutError,
)
from .market_data import MarketDataClient
from .mock import MockClobClient
from .rate_limiter import RateLimiter
from .ws import ClobWebSocketClient

logger = logging.getLogger(__name__)

__all__ = [
    "ClobAdapter",
    "MockClobClient",
    "MarketDataClient",
    "ClobClientProtocol",
    "ClobWebSocketClient",
    "ClobAuthSigner",
    "HMACSigner",
    "L1Headers",
    "L2Headers",
    "BuilderHeaders",
    "ClobError",
    "ClobAPIError",
    "ClobAuthError",
    "ClobCircuitOpenError",
    "ClobConfigError",
    "ClobMaxRetriesError",
    "ClobNetworkError",
    "ClobRateLimitError",
    "ClobServerError",
    "ClobTimeoutError",
    "CircuitBreaker",
    "RateLimiter",
    "build_l1_headers",
    "build_l2_headers",
    "build_hmac_signature",
    "build_builder_headers",
    "get_clob_client",
    "get_clob_breaker",
    "get_clob_rate_limiter",
    "reset_clob_resilience",
]


@runtime_checkable
class ClobClientProtocol(Protocol):
    """Minimum surface every CLOB client (real or mock) implements.

    Phase 4C widens the surface so the order-lifecycle manager can poll
    fills, cancel resting orders, and reconcile open-order books without
    coupling to ``ClobAdapter``-specific internals.
    """

    async def post_order(
        self,
        *,
        token_id: str,
        side: str,
        price: float,
        size: float,
        order_type: str = "GTC",
        tick_size: Optional[str] = None,
        neg_risk: Optional[bool] = None,
    ) -> dict: ...

    async def cancel_order(self, order_id: str) -> dict: ...

    async def cancel_all_orders(
        self, market: Optional[str] = None,
    ) -> dict: ...

    async def get_order(self, order_id: str) -> dict: ...

    async def get_fills(self, order_id: str) -> list[dict]: ...

    async def get_open_orders(
        self, market: Optional[str] = None,
    ) -> list[dict]: ...

    async def aclose(self) -> None: ...


# Module-level singletons survive per-call adapter construction in
# domain/execution/live.py. Both are lazily constructed on first
# get_clob_client() call so paper-mode test runs never instantiate
# them.
_breaker: Optional[CircuitBreaker] = None
_limiter: Optional[RateLimiter] = None


async def _on_circuit_open(name: str) -> None:
    """Telegram operator alert fired when the breaker trips.

    Imported lazily so the package stays importable in environments
    without the bot stack (CI smoke tests, mainnet preflight script).
    Failures inside the alert are swallowed by the breaker -- the alert
    must never keep the breaker stuck CLOSED.
    """
    try:
        from ...notifications import notify_operator
    except Exception as exc:  # noqa: BLE001 -- alert is best effort
        logger.error(
            "circuit breaker '%s' OPEN but Telegram notify unavailable: %s",
            name, exc,
        )
        return
    text = (
        "⛔️ *CLOB circuit OPEN*\n"
        f"breaker `{name}` tripped after consecutive transport failures. "
        "New orders are blocked until the breaker auto half-opens "
        "or an operator resets it via /ops."
    )
    try:
        await notify_operator(text)
    except Exception as exc:  # noqa: BLE001 -- best effort
        logger.error(
            "circuit breaker '%s' OPEN -- operator notify failed: %s",
            name, exc,
        )


def get_clob_breaker(
    settings: Optional[Settings] = None,
) -> CircuitBreaker:
    """Return the package-level CLOB circuit breaker (singleton).

    Constructed lazily from ``CIRCUIT_BREAKER_THRESHOLD`` /
    ``CIRCUIT_BREAKER_RESET_SECONDS``. The ops dashboard reads this
    instance to render circuit state.
    """
    global _breaker
    if _breaker is None:
        s = settings or get_settings()
        _breaker = CircuitBreaker(
            threshold=s.CIRCUIT_BREAKER_THRESHOLD,
            reset_seconds=float(s.CIRCUIT_BREAKER_RESET_SECONDS),
            on_open=_on_circuit_open,
            name="clob",
        )
    return _breaker


def get_clob_rate_limiter(
    settings: Optional[Settings] = None,
) -> RateLimiter:
    """Return the package-level CLOB rate limiter (singleton).

    Constructed lazily from ``CLOB_RATE_LIMIT_RPS``. Shared across every
    adapter instance built by ``get_clob_client`` so unrelated callers
    in the same process throttle against the same bucket.
    """
    global _limiter
    if _limiter is None:
        s = settings or get_settings()
        _limiter = RateLimiter(rps=float(s.CLOB_RATE_LIMIT_RPS))
    return _limiter


def reset_clob_resilience() -> None:
    """Test seam -- clear the breaker / limiter singletons so each test
    starts with a fresh CLOSED breaker and a full bucket. Production
    code never calls this.
    """
    global _breaker, _limiter
    _breaker = None
    _limiter = None


def get_clob_client(
    settings: Optional[Settings] = None,
) -> ClobClientProtocol:
    """Return a CLOB client honouring the ``USE_REAL_CLOB`` toggle.

    Default branch (``USE_REAL_CLOB=False``) returns ``MockClobClient`` and
    must NEVER touch the network or require Polymarket credentials. The
    real branch validates that every credential the adapter needs is set
    and raises ``ClobConfigError`` otherwise -- explicit fail-fast rather
    than silently degrading to mock mode (silent fallback would be a
    capital-safety footgun).

    Phase 4E: every real adapter shares the package-level breaker +
    limiter singletons so resilience state survives the per-call
    adapter construction pattern in ``domain.execution.live``.
    """
    s = settings or get_settings()
    if not s.USE_REAL_CLOB:
        return MockClobClient()

    missing: list[str] = []
    if not s.POLYMARKET_API_KEY:
        missing.append("POLYMARKET_API_KEY")
    if not s.POLYMARKET_API_SECRET:
        missing.append("POLYMARKET_API_SECRET")
    passphrase = s.POLYMARKET_API_PASSPHRASE or s.POLYMARKET_PASSPHRASE
    if not passphrase:
        missing.append("POLYMARKET_API_PASSPHRASE")
    if not s.POLYMARKET_PRIVATE_KEY:
        missing.append("POLYMARKET_PRIVATE_KEY")
    if missing:
        raise ClobConfigError(
            "USE_REAL_CLOB=True but the following env vars are unset: "
            + ", ".join(missing)
        )

    return ClobAdapter(
        api_key=s.POLYMARKET_API_KEY,  # type: ignore[arg-type]
        api_secret=s.POLYMARKET_API_SECRET,  # type: ignore[arg-type]
        passphrase=passphrase,  # type: ignore[arg-type]
        private_key=s.POLYMARKET_PRIVATE_KEY,  # type: ignore[arg-type]
        funder_address=s.POLYMARKET_FUNDER_ADDRESS,
        signature_type=s.POLYMARKET_SIGNATURE_TYPE,
        builder_api_key=s.POLYMARKET_BUILDER_API_KEY,
        builder_api_secret=s.POLYMARKET_BUILDER_API_SECRET,
        builder_passphrase=s.POLYMARKET_BUILDER_PASSPHRASE,
        circuit_breaker=get_clob_breaker(s),
        rate_limiter=get_clob_rate_limiter(s),
    )
