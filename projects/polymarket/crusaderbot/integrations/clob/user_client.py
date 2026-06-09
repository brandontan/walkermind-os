"""Per-user CLOB client (WARP/root-per-user-clob-client — Step 1 foundation).

Step 1 of the per-user on-chain execution lane designed in PR #1730. Owner-chosen
model: every user trades from **their own** Polymarket deposit wallet, with their
own key and their own on-chain funds (true cross-user isolation).

This module is the foundation only: a per-user analogue of ``get_clob_client``
with the same proven AsyncSecureClient → deposit-wallet + L2-creds resolution
that ``ensure_clob_credentials`` already runs for the single-wallet path
(merged in PR #1727 / #1729). No execution path is rewired here — router/live.py
keep calling the global ``get_clob_client(s)``. Step 4 of the lane threads
``user_id`` through and switches the wiring; Step 5 (SENTINEL) gates live.

Two structural requirements (per #1730 design + Gemini review):

* **Single-flight.** Concurrent ``get_user_clob_client(U)`` calls share one
  in-flight ``AsyncSecureClient.create`` per user — no key-decryption /
  network-derivation stampede.
* **Bounded eviction.** A long-running process serving many users does not grow
  unbounded; LRU eviction (capacity ``USER_CACHE_CAPACITY``) closes the evicted
  client.

Cross-user isolation invariant (the #1 invariant, owner-set):

* The cache is keyed by ``user_id`` only — there is no shared mutable global
  client.
* ``user_id`` is REQUIRED on every entry point; ``None`` / missing → hard fail
  with a structured warning log + ``PerUserClobIsolationError``. There is no
  fallback "default user" path.
* The vault-decrypted private key is in-memory only, scoped to the build
  closure; never logged, never returned, never persisted.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID

from ...config import Settings, get_settings
from .exceptions import ClobConfigError, ClobError
from .v2_client import ClobV2Client

logger = logging.getLogger(__name__)

__all__ = [
    "PerUserClobError",
    "PerUserClobIsolationError",
    "USER_CACHE_CAPACITY",
    "resolve_deposit_wallet_creds",
    "get_user_clob_client",
    "clear_user_clob_cache",
]


# Bounded per-user cache capacity. Sized for a multi-hundred-user bot; an LRU
# eviction at the boundary closes the evicted client.
USER_CACHE_CAPACITY = 256

# POLY_1271 (EIP-1271 / EIP-7702 deposit wallet). Per-user execution is only
# defined for this signature type — that is the whole reason the per-user lane
# exists (each user has their own deposit wallet). Any other signature type
# resolved via this path is a configuration drift and is rejected.
_POLY_1271_SIGNATURE_TYPE = 3


class PerUserClobError(ClobError):
    """A per-user CLOB-client resolution failed."""


class PerUserClobIsolationError(PerUserClobError):
    """Cross-user isolation invariant violated.

    Raised when ``get_user_clob_client`` is called without a valid ``user_id``
    (``None``, wrong type, etc.). Treated as a SAFETY-CRITICAL defect: a
    keying bug here = user A's order built with user B's funds. There is no
    silent fallback to a default identity.
    """


@dataclass
class _CachedClient:
    """One per-user client + the artifacts derived alongside it.

    ``wallet`` is the SDK-resolved deposit wallet address — the maker/funder
    the order client will sign against. Step 2 will persist this on the
    ``wallets`` row; Step 4 will use it for the pre-post assertion in the
    order path. Step 1 just returns it for callers that want to inspect.
    """
    client: ClobV2Client
    wallet: str
    creds: dict = field(repr=False)  # never logged
    created_at: float


# Module-level state. Access is async-serialised through ``_state_lock`` so the
# cache + single-flight maps are consistent across concurrent callers.
_state_lock: asyncio.Lock = asyncio.Lock()
_user_cache: "OrderedDict[UUID, _CachedClient]" = OrderedDict()
_inflight: dict[UUID, "asyncio.Task[_CachedClient]"] = {}


async def resolve_deposit_wallet_creds(
    private_key: str,
) -> tuple[str, dict]:
    """Resolve a signer's Polymarket deposit wallet + L2 credentials.

    Extracted from ``ensure_clob_credentials`` so per-user callers can reuse the
    proven path. Given a private key, the official ``polymarket`` SDK's
    ``AsyncSecureClient`` runs an on-chain factory check to pick the correct
    deterministic deposit wallet (beacon vs UUPS) and mints CLOB L2 credentials
    bound to that wallet.

    Returns ``(wallet_address, creds_dict)`` where ``creds_dict`` is
    ``{"api_key", "api_secret", "passphrase"}``. The caller MUST treat the
    credentials as secret material.

    Raises ``PerUserClobError`` if ``private_key`` is empty.
    """
    if not private_key:
        raise PerUserClobError("resolve_deposit_wallet_creds: private_key is empty")

    # Lazy import keeps the package importable in environments without the
    # ``polymarket`` SDK installed (CI smoke tests, paper-only runs). Mirrors
    # the lazy import used in ``ensure_clob_credentials``.
    from polymarket import AsyncSecureClient  # noqa: WPS433

    # wallet=None requests the SDK auto-derive (the single-wallet contract from
    # #1729). For a per-user key the operator never has a hardcoded address.
    sc = await AsyncSecureClient.create(private_key=private_key, wallet=None)
    try:
        creds_obj = sc.credentials
        wallet = sc.wallet
    finally:
        await sc.close()
    creds = {
        "api_key": creds_obj.key,
        "api_secret": creds_obj.secret,
        "passphrase": creds_obj.passphrase,
    }
    return wallet, creds


async def _build_and_cache(
    user_id: UUID,
    settings: Settings,
) -> _CachedClient:
    """Wrap ``_build_for_user`` + cache-populate as one awaitable, so the
    single-flight task carries the cache write through to every waiter.

    Cache eviction runs INSIDE the in-flight task so the slot is always live
    when waiters await it. The ``_inflight`` slot itself is cleaned up by the
    outermost caller in ``get_user_clob_client``.
    """
    entry = await _build_for_user(user_id, settings)
    async with _state_lock:
        await _evict_lru_if_full()
        _user_cache[user_id] = entry
        _user_cache.move_to_end(user_id)
    return entry


async def _build_for_user(
    user_id: UUID,
    settings: Settings,
) -> _CachedClient:
    """Decrypt the user's key, resolve the deposit wallet + creds, build the
    order client. Called inside the single-flight future for one user only.
    """
    # Lazy import: avoid pulling in the wallet/vault stack (and its DB
    # dependency) for callers that never resolve per-user clients (tests,
    # paper-only smoke runs).
    from ...wallet.vault import get_decrypted_pk  # noqa: WPS433

    pk = await get_decrypted_pk(user_id)
    if not pk:
        raise PerUserClobError(
            f"per_user_clob: user has no encrypted_key in vault (user_id={user_id})"
        )

    wallet, creds = await resolve_deposit_wallet_creds(pk)

    # Lazy import the breakers + limiters to avoid an import cycle through
    # ``clob/__init__.py`` (which itself imports this module's neighbours).
    from . import get_clob_breaker, get_clob_rate_limiter  # noqa: WPS433

    client = ClobV2Client(
        private_key=pk,
        funder_address=wallet,
        signature_type=_POLY_1271_SIGNATURE_TYPE,
        api_key=creds["api_key"],
        api_secret=creds["api_secret"],
        passphrase=creds["passphrase"],
        builder_code=settings.POLYMARKET_BUILDER_CODE,
        builder_address=settings.POLYMARKET_BUILDER_ADDRESS,
        circuit_breaker=get_clob_breaker(settings),
        rate_limiter=get_clob_rate_limiter(settings),
    )
    # pk goes out of scope at function return — never stored on the cache
    # entry, never logged. The client closure holds it internally for signing.
    return _CachedClient(
        client=client,
        wallet=wallet,
        creds=creds,
        created_at=time.monotonic(),
    )


async def _evict_lru_if_full() -> None:
    """LRU evict the oldest cache entry when at capacity. Must be called with
    ``_state_lock`` held. The evicted client's ``aclose`` runs in a background
    task — best effort, never blocks resolution of the new entry.
    """
    while len(_user_cache) >= USER_CACHE_CAPACITY:
        evicted_uid, evicted = _user_cache.popitem(last=False)
        logger.info(
            "per_user_clob: LRU evict user_id=%s (capacity=%d)",
            evicted_uid, USER_CACHE_CAPACITY,
        )
        # Fire-and-forget close. If aclose raises we still want the new entry
        # to land.
        asyncio.create_task(_safe_aclose(evicted.client))


async def _safe_aclose(client: ClobV2Client) -> None:
    try:
        await client.aclose()
    except Exception as exc:  # noqa: BLE001 - best effort
        logger.warning("per_user_clob: aclose failed during eviction: %s", exc)


async def get_user_clob_client(
    user_id: UUID,
    settings: Optional[Settings] = None,
) -> ClobV2Client:
    """Return the per-user CLOB client, building it lazily on first call.

    Behaviour:

    * **Cache hit** — returns the cached client, moves the entry to MRU.
    * **Cache miss + no in-flight** — registers a single-flight future,
      decrypts the user's key, resolves wallet+creds, builds the client.
      Concurrent callers for the same user await the same future.
    * **Cache miss + in-flight** — awaits the existing future. No duplicate
      decryption or AsyncSecureClient call.

    Hard requirements (cross-user isolation invariant):

    * ``user_id`` MUST be a ``UUID``. ``None`` / missing / wrong type raises
      ``PerUserClobIsolationError`` with a structured warning log. There is
      no fallback to a default identity.
    * ``USE_REAL_CLOB`` must be enabled (this path is only meaningful for the
      real CLOB; paper trading routes through ``get_clob_client`` → mock).

    Raises:
        PerUserClobIsolationError: ``user_id`` is missing or not a ``UUID``.
        ClobConfigError: ``USE_REAL_CLOB`` is disabled.
        PerUserClobError: vault has no encrypted_key for this user.
    """
    if not isinstance(user_id, UUID):
        # Structured warning so a SAFETY-CRITICAL routing bug surfaces in logs
        # even if the caller swallows the exception.
        logger.warning(
            "per_user_clob: ISOLATION VIOLATION — user_id missing or wrong type "
            "(value=%r, type=%s); refusing to build a CLOB client",
            user_id, type(user_id).__name__,
        )
        raise PerUserClobIsolationError(
            "get_user_clob_client requires a UUID user_id "
            "(cross-user isolation invariant)"
        )

    s = settings or get_settings()
    if not s.USE_REAL_CLOB:
        # Per-user clients only exist for the live CLOB path. Paper mode must
        # not silently fabricate one — the caller should route through the
        # mock client via ``get_clob_client(s)``.
        raise ClobConfigError(
            "get_user_clob_client called with USE_REAL_CLOB=False — "
            "paper mode must use get_clob_client() instead"
        )

    # Single in-flight Task per user. Every awaiter shields the same task so:
    #   * concurrent callers for the same user share ONE build (no stampede),
    #   * each awaiter receives + locally consumes the result/exception (no
    #     orphan "Future exception was never retrieved" warnings),
    #   * a caller's cancellation cannot bring down the shared task — other
    #     waiters still get their answer.
    async with _state_lock:
        cached = _user_cache.get(user_id)
        if cached is not None:
            _user_cache.move_to_end(user_id)  # MRU
            return cached.client

        task = _inflight.get(user_id)
        if task is None:
            task = asyncio.create_task(_build_and_cache(user_id, s))
            _inflight[user_id] = task

    try:
        entry = await asyncio.shield(task)
    except BaseException:
        # Drop the in-flight slot so a retry can re-derive. Whichever awaiter
        # first observes the failure clears it; the ``is task`` guard prevents
        # racing with a fresh resolution that has already been registered.
        async with _state_lock:
            if _inflight.get(user_id) is task:
                _inflight.pop(user_id, None)
        raise

    async with _state_lock:
        if _inflight.get(user_id) is task:
            _inflight.pop(user_id, None)
    return entry.client


async def clear_user_clob_cache() -> None:
    """Test seam — drop every cached per-user client and close it.

    Production code never calls this. Mirrors ``reset_clob_resilience`` for
    the resilience singletons.
    """
    async with _state_lock:
        entries = list(_user_cache.values())
        _user_cache.clear()
        _inflight.clear()
    for entry in entries:
        await _safe_aclose(entry.client)
