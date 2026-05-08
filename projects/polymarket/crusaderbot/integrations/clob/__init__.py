"""Polymarket CLOB adapter (Phase 4A).

This package introduces a thin REST adapter against
``https://clob.polymarket.com`` that signs requests directly
(EIP-712 for L1, HMAC-SHA256 for L2, optional builder headers)
without going through the ``py-clob-client`` SDK.

It is wired in through a factory (``get_clob_client``) that returns either
``MockClobClient`` (default — paper safe) or the real ``ClobAdapter``
based on the ``USE_REAL_CLOB`` setting. Until Phase 4B rewires the live
execution callers, this package is reachable only by tests + the manual
integration smoke script.

Activation contract:
    USE_REAL_CLOB=False -> MockClobClient (no network)
    USE_REAL_CLOB=True  -> ClobAdapter (still gated by the runtime
                           activation guards in domain.execution.live)

The factory NEVER raises on missing credentials when USE_REAL_CLOB=False —
that branch is the paper-safe default and must remain reachable in CI
without any Polymarket secrets.
"""
from __future__ import annotations

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
from .exceptions import (
    ClobAPIError,
    ClobAuthError,
    ClobConfigError,
    ClobError,
)
from .market_data import MarketDataClient
from .mock import MockClobClient

__all__ = [
    "ClobAdapter",
    "MockClobClient",
    "MarketDataClient",
    "ClobClientProtocol",
    "ClobAuthSigner",
    "HMACSigner",
    "L1Headers",
    "L2Headers",
    "BuilderHeaders",
    "ClobError",
    "ClobAPIError",
    "ClobAuthError",
    "ClobConfigError",
    "build_l1_headers",
    "build_l2_headers",
    "build_hmac_signature",
    "build_builder_headers",
    "get_clob_client",
]


@runtime_checkable
class ClobClientProtocol(Protocol):
    """Minimum surface every CLOB client (real or mock) implements.

    Kept narrow on purpose: today only ``post_order`` and ``cancel_order``
    are wired. Phase 4B will widen this once live callers migrate off
    ``integrations.polymarket._build_clob_client``.
    """

    async def post_order(
        self,
        *,
        token_id: str,
        side: str,
        price: float,
        size: float,
        order_type: str = "GTC",
    ) -> dict: ...

    async def cancel_order(self, order_id: str) -> dict: ...

    async def get_order(self, order_id: str) -> dict: ...

    async def aclose(self) -> None: ...


def get_clob_client(
    settings: Optional[Settings] = None,
) -> ClobClientProtocol:
    """Return a CLOB client honouring the ``USE_REAL_CLOB`` toggle.

    Default branch (``USE_REAL_CLOB=False``) returns ``MockClobClient`` and
    must NEVER touch the network or require Polymarket credentials. The
    real branch validates that every credential the adapter needs is set
    and raises ``ClobConfigError`` otherwise — explicit fail-fast rather
    than silently degrading to mock mode (silent fallback would be a
    capital-safety footgun).
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
    )
