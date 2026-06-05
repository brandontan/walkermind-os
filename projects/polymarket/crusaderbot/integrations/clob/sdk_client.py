"""PolymarketSdkClient -- order backend on the official ``polymarket-client``.

CLOB v2 migration (WARP/clob-v2-migration). The legacy ``ClobAdapter``
hand-builds the EIP-712 order via the archived ``py-clob-client`` (v1).
Polymarket's CLOB v2 (~Apr 2026) rejects that struct with
``400 order_version_mismatch``. This client delegates order construction +
signing + posting to ``polymarket.AsyncSecureClient`` (which produces the
v2 ``SignedOrder`` schema) while preserving the resilience contract the
rest of the system relies on:

  * Same ``ClobClientProtocol`` surface -- callers are unchanged.
  * The package-level CircuitBreaker + RateLimiter wrap every order op,
    so breaker state and throttling survive exactly as before.
  * py-sdk's own exception taxonomy is mapped onto the ``ClobError``
    hierarchy so the router / lifecycle / ops dashboard keep routing on
    typed errors.
  * A rejected order (py-sdk ``RejectedOrder``) is RAISED, never returned
    silently -- a swallowed rejection on the capital path is a footgun.

Lifecycle note: ``AsyncSecureClient.create()`` is network-heavy (it
validates the wallet and fetches deployment status) and stateful, so it
is built ONCE per client instance behind an ``asyncio.Lock`` and cached.
Because every Protocol order method is already ``async``, the heavyweight
init is hidden inside the first awaited call -- the synchronous
``get_clob_client()`` factory and its callers do not change.

Async-only -- no threading, no blocking I/O on the trading loop.

Known boundaries (documented for SENTINEL / follow-up lanes):
  * ``signature_type`` is NOT passed to py-sdk -- it derives the proxy
    type from ``wallet`` (the funder address). ``POLYMARKET_SIGNATURE_TYPE``
    is advisory under this backend; logged at init for operator awareness.
  * Only GTC limit orders are supported here. GTD / FOK / FAK / market
    orders raise ``ClobConfigError`` (py-sdk market path uses a different
    arg shape) -- a deliberate follow-up, not a silent mis-execution.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from .adapter import _trade_matches_order
from .circuit_breaker import CircuitBreaker
from .exceptions import (
    ClobAPIError,
    ClobAuthError,
    ClobConfigError,
    ClobError,
    ClobNetworkError,
    ClobRateLimitError,
    ClobServerError,
    ClobTimeoutError,
)
from .rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

DEFAULT_HOST = "https://clob.polymarket.com"
DEFAULT_CHAIN_ID = 137


class PolymarketSdkClient:
    """``ClobClientProtocol`` implementation backed by ``polymarket-client``.

    Constructed by ``get_clob_client`` when ``USE_REAL_CLOB`` and
    ``USE_PYSDK_CLOB`` are both set. Shares the package-level breaker +
    limiter singletons so resilience state is process-wide.
    """

    def __init__(
        self,
        *,
        private_key: str,
        funder_address: Optional[str] = None,
        signature_type: int = 2,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        passphrase: Optional[str] = None,
        builder_api_key: Optional[str] = None,
        builder_api_secret: Optional[str] = None,
        builder_passphrase: Optional[str] = None,
        host: str = DEFAULT_HOST,
        chain_id: int = DEFAULT_CHAIN_ID,
        nonce: int = 0,
        circuit_breaker: Optional[CircuitBreaker] = None,
        rate_limiter: Optional[RateLimiter] = None,
    ) -> None:
        self._private_key = private_key
        self._funder = funder_address
        self._signature_type = int(signature_type)
        self._api_creds = (api_key, api_secret, passphrase)
        self._builder_creds = (
            builder_api_key, builder_api_secret, builder_passphrase,
        )
        self._host = host.rstrip("/")
        self._chain_id = int(chain_id)
        self._nonce = int(nonce)
        self._breaker = circuit_breaker or CircuitBreaker(name="clob-pysdk")
        self._limiter = rate_limiter or RateLimiter(rps=0)
        self._client: Any = None
        self._owner_kw: Optional[str] = None      # cached owner-scope kwarg name
        self._owner_kw_resolved = False
        self._lock = asyncio.Lock()
        self._address = self._derive_address(private_key)
        if self._funder:
            logger.info(
                "clob-pysdk: signature_type=%s is advisory; py-sdk derives "
                "the proxy type from funder=%.10s…",
                self._signature_type, self._funder,
            )

    # ----- public properties (ops/factory parity) -------------------

    @property
    def address(self) -> str:
        return self._address

    @property
    def funder(self) -> Optional[str]:
        return self._funder

    @property
    def signature_type(self) -> int:
        return self._signature_type

    @property
    def has_builder_credentials(self) -> bool:
        return all(self._builder_creds)

    @property
    def circuit_breaker(self) -> CircuitBreaker:
        return self._breaker

    @property
    def rate_limiter(self) -> RateLimiter:
        return self._limiter

    # ----- internals ------------------------------------------------

    @staticmethod
    def _derive_address(private_key: str) -> str:
        try:
            from eth_account import Account  # noqa: WPS433
            return Account.from_key(private_key).address
        except Exception as exc:  # pragma: no cover - bad key surfaces at boot
            raise ClobAuthError(
                f"pysdk CLOB backend: invalid POLYMARKET_PRIVATE_KEY: {exc}"
            ) from exc

    async def _ensure(self) -> Any:
        """Build + cache the AsyncSecureClient once (network-heavy)."""
        if self._client is not None:
            return self._client
        async with self._lock:
            if self._client is not None:
                return self._client
            try:
                from polymarket import (  # noqa: WPS433
                    ApiKeyCreds,
                    AsyncSecureClient,
                    BuilderApiKey,
                )
            except Exception as exc:  # pragma: no cover - dep in requirements
                raise ClobConfigError(
                    f"polymarket-client required for pysdk CLOB backend: {exc}"
                ) from exc

            creds = None
            ak, asec, app = self._api_creds
            if ak and asec and app:
                creds = ApiKeyCreds(apiKey=ak, secret=asec, passphrase=app)
            builder = None
            bk, bs, bp = self._builder_creds
            if bk and bs and bp:
                builder = BuilderApiKey(key=bk, secret=bs, passphrase=bp)
            try:
                self._client = await AsyncSecureClient.create(
                    private_key=self._private_key,
                    wallet=self._funder,
                    credentials=creds,
                    api_key=builder,
                    nonce=self._nonce,
                )
            except Exception as exc:
                raise self._map_error(exc, "create_client")
            return self._client

    def _map_error(self, exc: BaseException, ctx: str) -> BaseException:
        """Map a py-sdk exception onto the ClobError taxonomy.

        Unknown / non-py-sdk exceptions are returned unchanged so genuine
        bugs are not masked as broker errors.
        """
        if isinstance(exc, ClobError):
            return exc
        try:
            from polymarket import (  # noqa: WPS433
                InsufficientAllowanceError,
                InsufficientLiquidityError,
                PolymarketError,
                RateLimitError,
                RequestRejectedError,
                SigningError,
                TimeoutError as PmTimeoutError,
                TransportError,
                UserInputError,
            )
        except Exception:  # pragma: no cover - dep in requirements
            return ClobNetworkError(f"{ctx}: {exc}")

        if isinstance(exc, RateLimitError):
            return ClobRateLimitError(status_code=429, path=ctx, body=str(exc))
        if isinstance(exc, RequestRejectedError):
            status = int(getattr(exc, "status", 0) or 0)
            # Only 401/403 are authn/authz failures. A 400 (and 404/409/422 etc.)
            # is a request/validation rejection -- e.g. "the orderbook does not
            # exist", bad price/tick, or a closed market -- and must NOT be
            # bucketed as auth, or ops/retry logic would react to the wrong cause.
            if status in (401, 403):
                return ClobAuthError(
                    f"{ctx}: {exc}", status_code=status, path=ctx, body=str(exc),
                )
            if status in (500, 502, 503, 504):
                return ClobServerError(status_code=status, path=ctx, body=str(exc))
            return ClobAPIError(status_code=status or 400, path=ctx, body=str(exc))
        if isinstance(exc, PmTimeoutError):
            return ClobTimeoutError(f"{ctx}: {exc}")
        if isinstance(exc, TransportError):
            return ClobNetworkError(f"{ctx}: {exc}")
        if isinstance(exc, (SigningError, UserInputError)):
            return ClobAuthError(
                f"{ctx}: {exc}", status_code=400, path=ctx, body=str(exc),
            )
        if isinstance(exc, (InsufficientLiquidityError, InsufficientAllowanceError)):
            return ClobAPIError(status_code=400, path=ctx, body=str(exc))
        if isinstance(exc, PolymarketError):
            return ClobAPIError(status_code=0, path=ctx, body=str(exc))
        return exc

    async def _collect(self, paginator: Any) -> list[Any]:
        items: list[Any] = []
        async for item in paginator:
            items.append(item)
        return items

    @staticmethod
    def _model_to_dict(obj: Any) -> dict:
        """Reduce an SDK response object to a plain mapping, shape-agnostically.

        polymarket-client models are not uniformly pydantic-v2: an open-order
        item can be a pydantic-v1 model (``.dict()``), a dataclass, or a
        ``__slots__``/attrs instance with an EMPTY ``__dict__``. The naive
        ``__dict__`` path then yields ``{}`` and the id/asset are silently lost
        (the run-#11 staging-proof defect). Try each known shape in order and
        return the first populated mapping."""
        # pydantic v2
        dump = getattr(obj, "model_dump", None)
        if callable(dump):
            try:
                out = dump()
            except Exception:  # noqa: BLE001 — fall through to next strategy
                out = None
            if isinstance(out, dict) and out:
                return out
        # pydantic v1 / generic ``.dict()``
        as_dict = getattr(obj, "dict", None)
        if callable(as_dict):
            try:
                out = as_dict()
            except Exception:  # noqa: BLE001 — fall through to next strategy
                out = None
            if isinstance(out, dict) and out:
                return out
        if isinstance(obj, dict):
            return dict(obj)
        # dataclass
        try:
            import dataclasses  # noqa: WPS433
            if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
                return dataclasses.asdict(obj)
        except Exception:  # noqa: BLE001 — fall through to next strategy
            pass
        # plain instance ``__dict__``
        data = getattr(obj, "__dict__", None)
        if isinstance(data, dict) and data:
            return dict(data)
        # ``__slots__`` / attrs instance (no usable ``__dict__``)
        slots: dict = {}
        for klass in type(obj).__mro__:
            for name in getattr(klass, "__slots__", ()) or ():
                if isinstance(name, str) and hasattr(obj, name):
                    slots[name] = getattr(obj, name)
        return slots

    # Attribute names the open-order id / asset may live under, across the
    # mapping path AND a direct getattr fallback (covers property/slots models
    # that ``_model_to_dict`` cannot enumerate).
    _OID_KEYS = ("id", "order_id", "orderID", "orderId")
    _ASSET_KEYS = ("asset_id", "token_id", "tokenID", "tokenId")

    def _order_to_dict(self, obj: Any) -> dict:
        """Open-order / get-order shape with id aliases the consumers read."""
        d = self._model_to_dict(obj)

        def _pick(keys: tuple[str, ...]) -> Any:
            for k in keys:
                v = d.get(k)
                if v not in (None, ""):
                    return v
            for k in keys:  # last resort: read straight off the SDK object
                v = getattr(obj, k, None)
                if v not in (None, ""):
                    return v
            return None

        oid = _pick(self._OID_KEYS)
        asset = _pick(self._ASSET_KEYS)
        if oid is None:
            # Never silently drop an order: name the real type/attrs so a shape
            # we still don't map surfaces in ops without another proof cycle.
            logger.warning(
                "clob-pysdk: open-order map found no id; type=%s public_attrs=%s",
                type(obj).__name__,
                [a for a in dir(obj) if not a.startswith("_")][:40],
            )
        d["id"] = d.get("id") or oid
        d["orderID"] = d.get("orderID") or oid
        d["order_id"] = d.get("order_id") or oid
        d["asset_id"] = d.get("asset_id") or asset
        return d

    def _accepted_to_dict(self, resp: Any) -> dict:
        d = self._model_to_dict(resp)
        if d.get("ok") is False or ("code" in d and "order_id" not in d):
            raise ClobAPIError(
                status_code=400,
                path="/order",
                body=str(d),
                message=(
                    f"CLOB rejected order: {d.get('code')} {d.get('message')}"
                ),
            )
        oid = d.get("order_id") or ""
        out: dict = {
            "success": True,
            "orderID": oid,
            "order_id": oid,
            "id": oid,
            "status": d.get("status"),
        }
        for k in ("making_amount", "taking_amount", "trade_ids", "transactions_hashes"):
            if k in d:
                out[k] = d[k]
        return out

    # ----- ClobClientProtocol --------------------------------------

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
    ) -> dict:
        ot = (order_type or "GTC").upper()
        if ot != "GTC":
            raise ClobConfigError(
                "pysdk CLOB backend supports GTC limit orders only "
                f"(got {ot!r}); GTD/FOK/FAK/market is a follow-up lane."
            )
        # tick_size / neg_risk are accepted for ClobClientProtocol parity but
        # NOT forwarded: py-sdk's create_limit_order resolves both from the
        # market itself (authoritative truth), so the caller's values are
        # advisory hints. We deliberately do NOT raise when they are set --
        # every live caller passes them, and py-sdk derives neg_risk from the
        # token's market, which is safer than trusting a caller hint. Logged
        # (not silently dropped) so a divergence is visible in ops.
        if tick_size is not None or neg_risk is not None:
            logger.debug(
                "clob-pysdk: tick_size=%s neg_risk=%s are advisory; py-sdk "
                "resolves both from market truth for token %s",
                tick_size, neg_risk, token_id,
            )
        client = await self._ensure()

        async def _do() -> dict:
            await self._limiter.acquire()
            try:
                signed = await client.create_limit_order(
                    token_id=token_id,
                    side=side.upper(),
                    price=price,
                    size=size,
                )
                resp = await client.post_order(signed)
            except Exception as exc:
                raise self._map_error(exc, "/order")
            return self._accepted_to_dict(resp)

        return await self._breaker.call(_do)

    async def cancel_order(self, order_id: str) -> dict:
        client = await self._ensure()

        async def _do() -> dict:
            await self._limiter.acquire()
            try:
                resp = await client.cancel_order(order_id=order_id)
            except Exception as exc:
                raise self._map_error(exc, "/order:cancel")
            return self._model_to_dict(resp)

        return await self._breaker.call(_do)

    async def cancel_all_orders(self, market: Optional[str] = None) -> dict:
        client = await self._ensure()

        async def _do() -> dict:
            await self._limiter.acquire()
            try:
                if market:
                    # b3 has no market-scoped cancel endpoint -- list then
                    # cancel by id so the kill-switch scope stays honoured.
                    items = await self._collect(
                        client.list_open_orders(market=market)
                    )
                    ids = [self._order_to_dict(o).get("id") for o in items]
                    ids = [i for i in ids if i]
                    if not ids:
                        return {"canceled": [], "not_canceled": {}}
                    resp = await client.cancel_orders(order_ids=ids)
                else:
                    resp = await client.cancel_all()
            except Exception as exc:
                raise self._map_error(exc, "/cancel-all")
            return self._model_to_dict(resp)

        return await self._breaker.call(_do)

    async def cancel_all(self) -> dict:
        return await self.cancel_all_orders()

    async def get_order(self, order_id: str) -> dict:
        client = await self._ensure()

        async def _do() -> dict:
            await self._limiter.acquire()
            try:
                order = await client.get_order(order_id=order_id)
            except Exception as exc:
                raise self._map_error(exc, "/data/order")
            return self._order_to_dict(order)

        return await self._breaker.call(_do)

    async def get_fills(
        self, order_id: str, *, market: Optional[str] = None,
    ) -> list[dict]:
        client = await self._ensure()
        await self._limiter.acquire()
        try:
            if market:
                pag = client.list_account_trades(market=market)
            else:
                # Proxy wallets (signature_type 1/2) record on-chain trades
                # under the FUNDER/proxy address, not the EOA signer -- query
                # the funder when set so fills are found for proxy accounts
                # (the staging/prod wallet config); fall back to the EOA.
                pag = client.list_account_trades(
                    maker_address=self._funder or self._address
                )
            items = await self._collect(pag)
        except Exception as exc:
            raise self._map_error(exc, "/data/trades")
        out: list[dict] = []
        for t in items:
            d = self._model_to_dict(t)
            if _trade_matches_order(d, order_id):
                out.append(d)
        return out

    def _owner_kwargs(self, fn: Any) -> dict:
        """Scope a list call by the proxy FUNDER when set.

        Proxy wallets (signature_type 1/2 + funder) record their orders/trades
        under the FUNDER address, not the EOA signer -- so a list query keyed on
        the signer returns nothing (mirrors the get_fills F1 fix). Pick whichever
        owner-style kwarg the installed pysdk's ``list_open_orders`` exposes, so
        this works regardless of the exact param name; if none is supported the
        call falls back to the SDK's default auth scoping. The resolved kwarg name
        is cached (the pysdk client is fixed per instance) so ``inspect.signature``
        runs once, not on every trading-loop read."""
        owner = self._funder or self._address
        if not owner:
            return {}
        if not self._owner_kw_resolved:
            self._owner_kw = self._detect_owner_kw(fn)
            self._owner_kw_resolved = True
        return {self._owner_kw: owner} if self._owner_kw else {}

    @staticmethod
    def _detect_owner_kw(fn: Any) -> Optional[str]:
        """Name of the owner-scope kwarg the pysdk list call accepts (or None).

        Skips POSITIONAL_ONLY params (passing them by keyword raises TypeError)."""
        try:
            import inspect  # noqa: WPS433
            params = inspect.signature(fn).parameters
        except (TypeError, ValueError):
            return None
        for name in ("maker_address", "owner", "owner_address", "maker", "address"):
            p = params.get(name)
            if p is not None and p.kind is not inspect.Parameter.POSITIONAL_ONLY:
                return name
        return None

    async def get_open_orders(
        self, market: Optional[str] = None,
    ) -> list[dict]:
        client = await self._ensure()

        async def _do() -> list[dict]:
            await self._limiter.acquire()
            try:
                kw = self._owner_kwargs(client.list_open_orders)
                if market:
                    kw["market"] = market
                pag = client.list_open_orders(**kw)
                items = await self._collect(pag)
            except Exception as exc:
                raise self._map_error(exc, "/data/orders")
            return [self._order_to_dict(o) for o in items]

        return await self._breaker.call(_do)

    async def aclose(self) -> None:
        client, self._client = self._client, None
        if client is None:
            return
        try:
            close = getattr(client, "close", None) or getattr(client, "aclose", None)
            if close is None:
                return
            res = close()
            if asyncio.iscoroutine(res):
                await res
        except Exception:  # noqa: BLE001 -- teardown must never raise
            logger.warning("clob-pysdk: client close failed", exc_info=True)
