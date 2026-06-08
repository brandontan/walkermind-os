"""ClobV2Client -- order backend on the official ``py-clob-client-v2`` SDK.

CLOB v2 cutover (WARP/clob-v2-cutover). This is the single-package successor to
the fragile two-library hybrid that preceded it:

  * ``ClobAdapter`` hand-built the EIP-712 order via the archived
    ``py-clob-client`` v1 -> Polymarket CLOB v2 rejected it
    (``400 order_version_mismatch``).
  * ``PolymarketSdkClient`` then bolted the official ``polymarket-client``
    (v2 transport) on top, needing three proxy-read workarounds
    (Page-flatten / shape-map / funder-scope) because that SDK returns awkward
    Page wrappers + ``__slots__`` models.

``py-clob-client-v2`` (stable 1.0.1) builds the **v2 order struct natively**
(``OrderArgsV2`` / ``SignatureTypeV2`` / native ``builder_code``), returns clean
dicts, and supports every order type -- so this client is materially simpler
than ``PolymarketSdkClient`` while preserving the exact contract callers depend
on:

  * Same ``ClobClientProtocol`` surface -- callers are unchanged.
  * The package-level CircuitBreaker + RateLimiter wrap every order op.
  * py-clob-client-v2's exception taxonomy is mapped onto ``ClobError`` so the
    router / lifecycle / ops dashboard keep routing on typed errors.
  * A rejected order is RAISED, never returned silently.

The v2 SDK is synchronous; its blocking calls are wrapped in
``asyncio.to_thread`` so the trading event loop is never stalled (the same
pattern the builder relayer already uses). The heavyweight client construction
(which may derive L2 credentials over the network) is built ONCE behind an
``asyncio.Lock`` and cached, hidden inside the first awaited order method.

Gated OFF by default (``USE_CLOB_V2=False``) -- the proven ``PolymarketSdkClient``
remains the active real path until this client is validated against the real
broker via the WARP-74 staging harness (``allow_fills=false``). No threading
(only ``to_thread`` offload), no blocking I/O on the loop, no silent failures.
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
# 32-byte zero sentinel py-clob-client-v2 uses for "no builder attribution".
_ZERO_BYTES32 = "0x" + ("00" * 32)
_SUPPORTED_ORDER_TYPES = frozenset({"GTC", "FOK", "FAK"})


class ClobV2Client:
    """``ClobClientProtocol`` implementation backed by ``py-clob-client-v2``.

    Constructed by ``get_clob_client`` when ``USE_REAL_CLOB`` and ``USE_CLOB_V2``
    are both set. Shares the package-level breaker + limiter singletons so
    resilience state is process-wide.
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
        builder_code: Optional[str] = None,
        builder_address: Optional[str] = None,
        host: str = DEFAULT_HOST,
        chain_id: int = DEFAULT_CHAIN_ID,
        circuit_breaker: Optional[CircuitBreaker] = None,
        rate_limiter: Optional[RateLimiter] = None,
    ) -> None:
        self._private_key = private_key
        self._funder = funder_address
        self._signature_type = int(signature_type)
        self._api_creds = (api_key, api_secret, passphrase)
        self._builder_code = builder_code
        self._builder_address = builder_address
        self._host = host.rstrip("/")
        self._chain_id = int(chain_id)
        self._breaker = circuit_breaker or CircuitBreaker(name="clob-v2")
        self._limiter = rate_limiter or RateLimiter(rps=0)
        self._client: Any = None
        self._lock = asyncio.Lock()
        self._address = self._derive_address(private_key)

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
        return bool(self._builder_code and self._builder_code != _ZERO_BYTES32)

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
                f"clob-v2 backend: invalid POLYMARKET_PRIVATE_KEY: {exc}"
            ) from exc

    async def _ensure(self) -> Any:
        """Build + cache the sync v2 ClobClient once (may derive creds online)."""
        if self._client is not None:
            return self._client
        async with self._lock:
            if self._client is not None:
                return self._client
            try:
                self._client = await asyncio.to_thread(self._build_client)
            except Exception as exc:
                raise self._map_error(exc, "create_client")
            return self._client

    def _build_client(self) -> Any:
        """Synchronous client construction -- runs in a worker thread.

        Builds the v2 ``ClobClient`` with the Gnosis-Safe signature type +
        funder + (optional) builder attribution. When no L2 API creds are
        supplied, derive them from the signer (the v2 SDK's documented flow)
        so a private-key-only deployment still authenticates.
        """
        try:
            from py_clob_client_v2 import (  # noqa: WPS433
                ApiCreds,
                BuilderConfig,
                ClobClient,
            )
        except Exception as exc:  # pragma: no cover - dep in requirements
            raise ClobConfigError(
                f"py-clob-client-v2 required for the v2 CLOB backend: {exc}"
            ) from exc

        ak, asec, app = self._api_creds
        creds = (
            ApiCreds(api_key=ak, api_secret=asec, api_passphrase=app)
            if (ak and asec and app)
            else None
        )
        builder_config = None
        if self._builder_code and self._builder_code != _ZERO_BYTES32:
            builder_config = BuilderConfig(
                builder_address=self._builder_address or "",
                builder_code=self._builder_code,
            )

        client = ClobClient(
            self._host,
            self._chain_id,
            key=self._private_key,
            creds=creds,
            signature_type=self._signature_type,
            funder=self._funder,
            builder_config=builder_config,
        )
        if creds is None:
            # Derive L2 creds from the signer and attach them for trade auth.
            client.set_api_creds(client.create_or_derive_api_key())
        return client

    def _map_error(self, exc: BaseException, ctx: str) -> BaseException:
        """Map a py-clob-client-v2 exception onto the ClobError taxonomy.

        Unknown / non-SDK exceptions are returned unchanged so genuine bugs are
        not masked as broker errors. Only 401/403 are auth; a 400/404/409/422 is
        a request/validation rejection (bad price/tick, closed market, missing
        orderbook) and must NOT be bucketed as auth or ops/retry mis-reacts.
        """
        if isinstance(exc, ClobError):
            return exc
        status = getattr(exc, "status_code", None)
        if status is None:
            resp = getattr(exc, "resp", None) or getattr(exc, "response", None)
            status = getattr(resp, "status_code", None)
        msg = getattr(exc, "error_msg", None) or str(exc)
        try:
            status = int(status) if status is not None else None
        except (TypeError, ValueError):
            status = None

        if status is not None:
            if status == 429:
                return ClobRateLimitError(status_code=429, path=ctx, body=msg)
            if status in (401, 403):
                return ClobAuthError(
                    f"{ctx}: {msg}", status_code=status, path=ctx, body=msg,
                )
            if status in (500, 502, 503, 504):
                return ClobServerError(status_code=status, path=ctx, body=msg)
            return ClobAPIError(status_code=status, path=ctx, body=msg)

        # No HTTP status -> classify by the SDK's exception class names without
        # importing them (keeps the mapper resilient across SDK versions).
        name = type(exc).__name__
        low = f"{name}: {msg}".lower()
        if isinstance(exc, (TimeoutError,)) or "timeout" in low:
            return ClobTimeoutError(f"{ctx}: {msg}")
        if name in ("PolyApiException",) or "connect" in low or "transport" in low:
            return ClobNetworkError(f"{ctx}: {msg}")
        if name == "PolyException":
            return ClobAPIError(status_code=0, path=ctx, body=msg)
        return exc

    @staticmethod
    def _to_dict(obj: Any) -> dict:
        """Reduce a v2 SDK response to a plain mapping.

        py-clob-client-v2 returns plain dicts for order/trade reads; this stays
        tolerant of dataclass/pydantic shapes so a minor SDK change cannot
        silently drop fields.
        """
        if isinstance(obj, dict):
            return dict(obj)
        for attr in ("model_dump", "dict"):
            fn = getattr(obj, attr, None)
            if callable(fn):
                try:
                    out = fn()
                except Exception:  # noqa: BLE001 - try next strategy
                    out = None
                if isinstance(out, dict) and out:
                    return out
        data = getattr(obj, "__dict__", None)
        return dict(data) if isinstance(data, dict) else {}

    _OID_KEYS = ("id", "order_id", "orderID", "orderId")
    _ASSET_KEYS = ("asset_id", "token_id", "tokenID", "tokenId")

    def _order_to_dict(self, obj: Any) -> dict:
        """Order shape with the id/asset aliases every consumer reads."""
        d = self._to_dict(obj)

        def _pick(keys: tuple[str, ...]) -> Any:
            for k in keys:
                v = d.get(k)
                if v not in (None, ""):
                    return v
            for k in keys:
                v = getattr(obj, k, None)
                if v not in (None, ""):
                    return v
            return None

        oid = _pick(self._OID_KEYS)
        asset = _pick(self._ASSET_KEYS)
        if oid is None:
            logger.warning(
                "clob-v2: order map found no id; type=%s keys=%s",
                type(obj).__name__, list(d)[:20],
            )
        d["id"] = d.get("id") or oid
        d["orderID"] = d.get("orderID") or oid
        d["order_id"] = d.get("order_id") or oid
        d["asset_id"] = d.get("asset_id") or asset
        return d

    def _accepted_to_dict(self, resp: Any) -> dict:
        """Normalize a post_order response; RAISE on a rejected order."""
        d = self._to_dict(resp)
        success = d.get("success")
        oid = d.get("orderID") or d.get("orderId") or d.get("order_id") or ""
        if success is False or (not oid and (d.get("errorMsg") or d.get("error"))):
            raise ClobAPIError(
                status_code=400,
                path="/order",
                body=str(d),
                message=f"CLOB rejected order: {d.get('errorMsg') or d.get('error')}",
            )
        out: dict = {
            "success": True,
            "orderID": oid,
            "order_id": oid,
            "id": oid,
            "status": d.get("status"),
        }
        for k in ("making_amount", "takingAmount", "taking_amount",
                  "makingAmount", "transactionsHashes", "transactions_hashes"):
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
        if ot not in _SUPPORTED_ORDER_TYPES:
            # GTD needs an explicit expiration the Protocol does not carry; a
            # dedicated arg is a follow-up rather than a silent mis-execution.
            raise ClobConfigError(
                f"clob-v2 backend: order_type {ot!r} unsupported here "
                f"(supported: {sorted(_SUPPORTED_ORDER_TYPES)}; GTD needs an "
                "expiration -- follow-up lane)."
            )
        client = await self._ensure()

        def _build_and_post() -> Any:
            from py_clob_client_v2 import (  # noqa: WPS433
                OrderArgs,
                OrderType,
                PartialCreateOrderOptions,
            )
            args = OrderArgs(
                token_id=token_id,
                price=float(price),
                size=float(size),
                side=side.upper(),
                builder_code=self._builder_code or _ZERO_BYTES32,
            )
            opts = None
            if tick_size is not None or neg_risk is not None:
                opts = PartialCreateOrderOptions(
                    tick_size=tick_size, neg_risk=neg_risk,
                )
            return client.create_and_post_order(args, opts, getattr(OrderType, ot))

        async def _do() -> dict:
            await self._limiter.acquire()
            try:
                resp = await asyncio.to_thread(_build_and_post)
            except Exception as exc:
                raise self._map_error(exc, "/order")
            return self._accepted_to_dict(resp)

        return await self._breaker.call(_do)

    async def cancel_order(self, order_id: str) -> dict:
        client = await self._ensure()

        def _cancel() -> Any:
            from py_clob_client_v2 import OrderPayload  # noqa: WPS433
            return client.cancel_order(OrderPayload(orderID=order_id))

        async def _do() -> dict:
            await self._limiter.acquire()
            try:
                resp = await asyncio.to_thread(_cancel)
            except Exception as exc:
                raise self._map_error(exc, "/order:cancel")
            return self._to_dict(resp)

        return await self._breaker.call(_do)

    async def cancel_all_orders(self, market: Optional[str] = None) -> dict:
        client = await self._ensure()

        def _cancel() -> Any:
            if market:
                from py_clob_client_v2 import OrderMarketCancelParams  # noqa: WPS433
                return client.cancel_market_orders(
                    OrderMarketCancelParams(market=market)
                )
            return client.cancel_all()

        async def _do() -> dict:
            await self._limiter.acquire()
            try:
                resp = await asyncio.to_thread(_cancel)
            except Exception as exc:
                raise self._map_error(exc, "/cancel-all")
            return self._to_dict(resp)

        return await self._breaker.call(_do)

    async def cancel_all(self) -> dict:
        return await self.cancel_all_orders()

    async def get_order(self, order_id: str) -> dict:
        client = await self._ensure()

        async def _do() -> dict:
            await self._limiter.acquire()
            try:
                order = await asyncio.to_thread(client.get_order, order_id)
            except Exception as exc:
                raise self._map_error(exc, "/data/order")
            return self._order_to_dict(order)

        return await self._breaker.call(_do)

    async def get_fills(
        self, order_id: str, *, market: Optional[str] = None,
    ) -> list[dict]:
        client = await self._ensure()

        def _trades() -> Any:
            from py_clob_client_v2.clob_types import TradeParams  # noqa: WPS433
            # Proxy wallets (signature_type 1/2) record trades under the FUNDER
            # address, not the EOA signer -- query the funder when set.
            params = TradeParams(
                maker_address=self._funder or self._address,
                market=market,
            )
            return client.get_trades(params)

        await self._limiter.acquire()
        try:
            items = await asyncio.to_thread(_trades)
        except Exception as exc:
            raise self._map_error(exc, "/data/trades")
        out: list[dict] = []
        for t in items or []:
            d = self._to_dict(t)
            if _trade_matches_order(d, order_id):
                out.append(d)
        return out

    async def get_open_orders(
        self, market: Optional[str] = None,
    ) -> list[dict]:
        client = await self._ensure()

        def _open() -> Any:
            from py_clob_client_v2 import OpenOrderParams  # noqa: WPS433
            params = OpenOrderParams(market=market) if market else None
            return client.get_open_orders(params)

        async def _do() -> list[dict]:
            await self._limiter.acquire()
            try:
                items = await asyncio.to_thread(_open)
            except Exception as exc:
                raise self._map_error(exc, "/data/orders")
            return [self._order_to_dict(o) for o in (items or [])]

        return await self._breaker.call(_do)

    async def aclose(self) -> None:
        client, self._client = self._client, None
        if client is None:
            return
        close = getattr(client, "close", None) or getattr(client, "aclose", None)
        if close is None:
            return
        try:
            res = close()
            if asyncio.iscoroutine(res):
                await res
        except Exception:  # noqa: BLE001 -- teardown must never raise
            logger.warning("clob-v2: client close failed", exc_info=True)
