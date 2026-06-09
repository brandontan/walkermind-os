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
from .sdk_client import PolymarketSdkClient
from .user_client import (
    PerUserClobError,
    PerUserClobIsolationError,
    USER_CACHE_CAPACITY,
    clear_user_clob_cache,
    get_user_clob_client,
    resolve_deposit_wallet_creds,
)
from .v2_client import ClobV2Client
from .ws import ClobWebSocketClient

logger = logging.getLogger(__name__)

__all__ = [
    "ClobAdapter",
    "PolymarketSdkClient",
    "ClobV2Client",
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
    "ensure_clob_credentials",
    "PerUserClobError",
    "PerUserClobIsolationError",
    "USER_CACHE_CAPACITY",
    "clear_user_clob_cache",
    "get_user_clob_client",
    "resolve_deposit_wallet_creds",
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

# Auto-derived credential cache (populated by ensure_clob_credentials at boot).
# Only used when POLYMARKET_API_KEY is absent from env. Never persisted.
_derived: Optional[dict] = None

# POLY_1271 deposit wallet resolved by AsyncSecureClient from the signer key
# (the SDK auto-derives the *current* deterministic deposit wallet — beacon vs
# UUPS — via an on-chain factory check). Cached alongside ``_derived`` so the
# order path can use it as the maker/funder without a hardcoded address.
_derived_wallet: Optional[str] = None


async def ensure_clob_credentials(
    settings: Optional[Settings] = None,
) -> None:
    """Derive and cache Polymarket API credentials from POLYMARKET_PRIVATE_KEY.

    Call once at application startup when USE_REAL_CLOB=True but
    POLYMARKET_API_KEY/SECRET/PASSPHRASE are not set in the environment.
    Credentials are stored in the module-level ``_derived`` dict and
    consumed by ``get_clob_client()`` transparently.

    No-op when:
      * USE_REAL_CLOB=False (paper mode — credentials not needed)
      * POLYMARKET_API_KEY already set in env (manual creds take priority)
      * POLYMARKET_PRIVATE_KEY not set (nothing to derive from)

    Raises ``ClobAuthError`` / ``ClobNetworkError`` on failure so the
    operator sees the error immediately at boot rather than on the first
    live order.
    """
    global _derived, _derived_wallet
    s = settings or get_settings()
    if not s.USE_REAL_CLOB:
        return
    # For POLY_1271 deposit wallets, an env-provided api key (e.g. a builder/EOA
    # key) cannot authenticate the deposit-wallet maker — always derive via
    # AsyncSecureClient below. Other wallet types honour an env-provided key.
    _sig_type = int(getattr(s, "POLYMARKET_SIGNATURE_TYPE", 0) or 0)
    if s.POLYMARKET_API_KEY and _sig_type != 3:
        logger.info("clob: POLYMARKET_API_KEY set in env — skipping auto-derive")
        return
    if not s.POLYMARKET_PRIVATE_KEY:
        logger.warning("clob: USE_REAL_CLOB=True but POLYMARKET_PRIVATE_KEY not set — cannot derive credentials")
        return

    # POLY_1271 deposit wallets (EIP-7702 smart accounts): py-clob-client-v2's L1
    # auth cannot mint CLOB creds for them (upstream #70 — every L1 attempt returns
    # "Invalid L1 Request headers"). The OFFICIAL polymarket SDK's AsyncSecureClient
    # resolves the deposit wallet and derives valid L2 creds; we cache those so the
    # proven ClobV2Client order path (correct 1271 order signing) authenticates.
    if int(getattr(s, "POLYMARKET_SIGNATURE_TYPE", 0) or 0) == 3:
        from polymarket import AsyncSecureClient  # noqa: WPS433

        # Pass the configured funder if set (validated against the signer); else
        # None so the SDK auto-derives the signer's current deposit wallet. Either
        # way we cache the SDK-resolved wallet as the authoritative maker/funder.
        _requested = s.POLYMARKET_FUNDER_ADDRESS or None
        logger.info(
            "clob: resolving POLY_1271 deposit wallet via AsyncSecureClient "
            "(requested=%s) …", _requested or "auto-derive",
        )
        sc = await AsyncSecureClient.create(
            private_key=s.POLYMARKET_PRIVATE_KEY,
            wallet=_requested,
        )
        try:
            creds = sc.credentials
            _derived_wallet = sc.wallet
        finally:
            await sc.close()
        _derived = {
            "api_key": creds.key,
            "api_secret": creds.secret,
            "passphrase": creds.passphrase,
        }
        logger.info(
            "clob: POLY_1271 deposit wallet resolved=%s, creds derived (key=%.8s…)",
            _derived_wallet, _derived["api_key"],
        )
        return

    logger.info("clob: deriving API credentials from POLYMARKET_PRIVATE_KEY …")
    tmp = ClobAdapter(
        api_key="",
        api_secret="",
        passphrase="",
        private_key=s.POLYMARKET_PRIVATE_KEY,
        funder_address=effective_funder(s),
        signature_type=s.POLYMARKET_SIGNATURE_TYPE,
        circuit_breaker=get_clob_breaker(s),
        rate_limiter=get_clob_rate_limiter(s),
    )
    creds = await tmp.derive_api_credentials()
    _derived = {
        "api_key": creds.get("apiKey") or creds.get("api_key", ""),
        "api_secret": creds.get("secret") or creds.get("api_secret", ""),
        "passphrase": creds.get("passphrase", ""),
    }
    logger.info(
        "clob: API credentials auto-derived (key=%.8s…)", _derived["api_key"]
    )


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


def effective_credentials(
    settings: Optional[Settings] = None,
) -> tuple[str, str, str]:
    """Resolve the CLOB API credentials the same way everywhere.

    Env vars take priority; fall back to the auto-derived cache (`_derived`,
    populated by ``ensure_clob_credentials`` when creds are not set in env).
    Returns ``(api_key, api_secret, passphrase)``. Used by both the REST client
    and the WebSocket subscribe frame so the WS does not silently send empty
    auth when credentials were auto-derived (which the broker rejects, causing
    an endless reconnect loop).
    """
    s = settings or get_settings()
    d = _derived or {}
    # POLY_1271 deposit wallets: the AsyncSecureClient-derived creds in ``_derived``
    # are the ONLY ones bound to the deposit wallet, so they take priority over any
    # env-provided api key (which for a deposit wallet would be a wrong builder/EOA
    # key). Every other wallet type keeps env-first precedence.
    if int(getattr(s, "POLYMARKET_SIGNATURE_TYPE", 0) or 0) == 3 and d.get("api_key"):
        return d.get("api_key", ""), d.get("api_secret", ""), d.get("passphrase", "")
    api_key = s.POLYMARKET_API_KEY or d.get("api_key", "")
    api_secret = s.POLYMARKET_API_SECRET or d.get("api_secret", "")
    passphrase = (
        s.POLYMARKET_API_PASSPHRASE
        or s.POLYMARKET_PASSPHRASE
        or d.get("passphrase", "")
    )
    return api_key, api_secret, passphrase


def effective_funder(settings: Optional[Settings] = None) -> Optional[str]:
    """Resolve the maker/funder address.

    For POLY_1271 deposit wallets, prefer the SDK-resolved deposit wallet
    (``_derived_wallet``, set by ``ensure_clob_credentials`` via
    ``AsyncSecureClient``) so the operator does not have to look up and hardcode
    ``POLYMARKET_FUNDER_ADDRESS`` — the configured key alone is enough. Every
    other wallet type keeps the env-configured funder.
    """
    s = settings or get_settings()
    if int(getattr(s, "POLYMARKET_SIGNATURE_TYPE", 0) or 0) == 3 and _derived_wallet:
        return _derived_wallet
    return s.POLYMARKET_FUNDER_ADDRESS


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

    # POLY_1271 (deposit wallet) orders require a resolved maker/funder. Fail fast
    # for ALL backends here rather than building any client with funder=None: a
    # None funder fails opaquely at order-signing time (V2 / adapter) or forces a
    # slow on-the-fly AsyncSecureClient derivation on the trading hot path (pysdk).
    # effective_funder returns the AsyncSecureClient-resolved deposit wallet (cached
    # by ensure_clob_credentials at startup) or the env POLYMARKET_FUNDER_ADDRESS.
    if int(getattr(s, "POLYMARKET_SIGNATURE_TYPE", 0) or 0) == 3 and not effective_funder(s):
        raise ClobConfigError(
            "POLY_1271 (deposit wallet) maker unresolved: run "
            "ensure_clob_credentials() at startup (it auto-derives the deposit "
            "wallet via AsyncSecureClient) or set POLYMARKET_FUNDER_ADDRESS."
        )

    # Resolve credentials: env vars take priority; fall back to auto-derived cache.
    api_key, api_secret, passphrase = effective_credentials(s)

    # CLOB v2 cutover (WARP/clob-v2-cutover): py-clob-client-v2 single-package
    # backend, native v2 order struct + builder attribution. Takes precedence
    # over USE_PYSDK_CLOB when enabled. Default OFF until staging-proven.
    if s.USE_CLOB_V2:
        if not s.POLYMARKET_PRIVATE_KEY:
            raise ClobConfigError(
                "USE_CLOB_V2=True but POLYMARKET_PRIVATE_KEY is unset"
            )
        # Fail fast on a half-configured builder attribution: a non-zero builder
        # code with no builder address yields invalid/zero-address attribution.
        _zero32 = "0x" + ("00" * 32)
        if (
            s.POLYMARKET_BUILDER_CODE
            and s.POLYMARKET_BUILDER_CODE != _zero32
            and not s.POLYMARKET_BUILDER_ADDRESS
        ):
            raise ClobConfigError(
                "POLYMARKET_BUILDER_CODE is set but POLYMARKET_BUILDER_ADDRESS "
                "is unset — builder attribution needs both"
            )
        return ClobV2Client(
            private_key=s.POLYMARKET_PRIVATE_KEY,
            funder_address=effective_funder(s),
            signature_type=s.POLYMARKET_SIGNATURE_TYPE,
            api_key=api_key or None,
            api_secret=api_secret or None,
            passphrase=passphrase or None,
            builder_code=s.POLYMARKET_BUILDER_CODE,
            builder_address=s.POLYMARKET_BUILDER_ADDRESS,
            circuit_breaker=get_clob_breaker(s),
            rate_limiter=get_clob_rate_limiter(s),
        )

    # CLOB v2 backend (WARP/clob-v2-migration): delegate order build/sign/post
    # to the official polymarket-client so the v2 SignedOrder schema is used.
    # py-sdk derives L2 creds from the private key when none are supplied, so
    # only POLYMARKET_PRIVATE_KEY is strictly required here.
    if s.USE_PYSDK_CLOB:
        if not s.POLYMARKET_PRIVATE_KEY:
            raise ClobConfigError(
                "USE_PYSDK_CLOB=True but POLYMARKET_PRIVATE_KEY is unset"
            )
        return PolymarketSdkClient(
            private_key=s.POLYMARKET_PRIVATE_KEY,
            funder_address=effective_funder(s),
            signature_type=s.POLYMARKET_SIGNATURE_TYPE,
            api_key=api_key or None,
            api_secret=api_secret or None,
            passphrase=passphrase or None,
            builder_api_key=s.POLYMARKET_BUILDER_API_KEY,
            builder_api_secret=s.POLYMARKET_BUILDER_API_SECRET,
            builder_passphrase=s.POLYMARKET_BUILDER_PASSPHRASE,
            circuit_breaker=get_clob_breaker(s),
            rate_limiter=get_clob_rate_limiter(s),
        )

    missing: list[str] = []
    if not api_key:
        missing.append("POLYMARKET_API_KEY (or run ensure_clob_credentials() at startup)")
    if not api_secret:
        missing.append("POLYMARKET_API_SECRET")
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
        api_key=api_key,
        api_secret=api_secret,
        passphrase=passphrase,
        private_key=s.POLYMARKET_PRIVATE_KEY,  # type: ignore[arg-type]
        funder_address=effective_funder(s),
        signature_type=s.POLYMARKET_SIGNATURE_TYPE,
        builder_api_key=s.POLYMARKET_BUILDER_API_KEY,
        builder_api_secret=s.POLYMARKET_BUILDER_API_SECRET,
        builder_passphrase=s.POLYMARKET_BUILDER_PASSPHRASE,
        circuit_breaker=get_clob_breaker(s),
        rate_limiter=get_clob_rate_limiter(s),
    )
