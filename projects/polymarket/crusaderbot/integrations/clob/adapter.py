"""ClobAdapter -- REST client wrapping Polymarket CLOB authenticated endpoints.

Phase 4A introduced the basic REST surface (post / cancel / get). Phase 4E
adds production-grade resilience around it:

  * Typed exception classification (auth / rate-limit / server / timeout
    / network / max-retries) replacing string-matching on httpx errors.
  * Token-bucket rate limiter applied before every outbound call so the
    broker's per-account 429 ceiling is unreachable in steady state.
  * Circuit breaker wrapping ``post_order``, ``cancel_order``, and
    ``get_order``; OPEN raises ``ClobCircuitOpenError`` immediately with
    no broker call. The ``on_open`` callback (wired in the package
    factory) pages the operator on Telegram.

Hard rules respected:
  * No silent failures -- every non-2xx HTTP response or transport
    exception raises a typed ``ClobError`` subclass.
  * Auth-class errors (400/401/403) are NOT retried (re-signing wouldn't
    help and a duplicate POST after broker accept is a capital-safety
    footgun).
  * Async-only -- no blocking I/O on the trading loop.
  * Builder headers attached when the corresponding credentials are
    configured; otherwise omitted (orders still post, just without
    attribution).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .auth import (
    ClobAuthSigner,
    DEFAULT_CHAIN_ID,
    build_builder_headers,
    build_l1_headers,
    build_l2_headers,
)
from .circuit_breaker import CircuitBreaker
from .exceptions import (
    ClobAPIError,
    ClobAuthError,
    ClobMaxRetriesError,
    ClobNetworkError,
    ClobRateLimitError,
    ClobServerError,
    ClobTimeoutError,
)
from .rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

DEFAULT_HOST = "https://clob.polymarket.com"
DEFAULT_TIMEOUT = 10.0
DEFAULT_MAX_RETRIES = 3

# Retryable exception classes -- everything else (notably ClobAuthError
# and ClobAPIError for non-auth 4xx) propagates on first occurrence.
RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    ClobRateLimitError,
    ClobServerError,
    ClobTimeoutError,
    ClobNetworkError,
)


def _trade_matches_order(trade: dict, order_id: str) -> bool:
    """True if a Polymarket trade row references the given order id.

    Checks both top-level fields (``taker_order_id`` / ``maker_order_id`` /
    ``order_id`` / ``orderID``) and the nested ``maker_orders[].order_id``
    array -- Polymarket's Trade Object stores maker-side order hashes
    inside that array, not as a top-level field, so resting GTC/GTD
    fills would otherwise be dropped (Codex P2 review).
    """
    if not order_id:
        return False
    if (
        trade.get("taker_order_id") == order_id
        or trade.get("maker_order_id") == order_id
        or trade.get("order_id") == order_id
        or trade.get("orderID") == order_id
    ):
        return True
    maker_orders = trade.get("maker_orders") or trade.get("makerOrders")
    if isinstance(maker_orders, list):
        for mo in maker_orders:
            if not isinstance(mo, dict):
                continue
            if (
                mo.get("order_id") == order_id
                or mo.get("orderID") == order_id
                or mo.get("id") == order_id
            ):
                return True
    return False


def _classify_http_error(
    status_code: int, *, path: str, body: str
) -> Exception:
    """Map an HTTP status to the right typed exception.

    Used by ``_signed_request`` so the caller receives a typed error
    that downstream layers (router, breaker, ops dashboard) can route
    on without re-parsing the status code.
    """
    if status_code in (400, 401, 403):
        return ClobAuthError(
            f"CLOB rejected auth on {path}: {status_code} {(body or '')[:200]}",
            status_code=status_code,
            path=path,
            body=body,
        )
    if status_code == 429:
        return ClobRateLimitError(
            status_code=status_code, path=path, body=body,
        )
    if status_code in (500, 502, 503, 504):
        return ClobServerError(
            status_code=status_code, path=path, body=body,
        )
    return ClobAPIError(
        status_code=status_code, path=path, body=body,
    )


class ClobAdapter:
    """REST client for Polymarket CLOB authenticated endpoints.

    Attributes are kept private (single underscore) -- the public surface
    is the async methods. Tests construct with an injected ``transport``
    via ``httpx.MockTransport`` to avoid network I/O.

    The optional ``circuit_breaker`` and ``rate_limiter`` are intended to
    be passed in by the package factory so they survive across adapter
    instances (per-call adapter construction is the live-execution
    pattern). When omitted (e.g. unit tests), the adapter still behaves
    correctly -- the limiter is a no-op and the breaker is a fresh
    CLOSED instance.
    """

    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        passphrase: str,
        private_key: str,
        funder_address: Optional[str] = None,
        signature_type: int = 2,
        builder_api_key: Optional[str] = None,
        builder_api_secret: Optional[str] = None,
        builder_passphrase: Optional[str] = None,
        host: str = DEFAULT_HOST,
        chain_id: int = DEFAULT_CHAIN_ID,
        timeout: float = DEFAULT_TIMEOUT,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        circuit_breaker: Optional[CircuitBreaker] = None,
        rate_limiter: Optional[RateLimiter] = None,
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._passphrase = passphrase
        self._signer = ClobAuthSigner(private_key=private_key, chain_id=chain_id)
        self._funder = funder_address or self._signer.address
        self._signature_type = int(signature_type)
        self._builder_api_key = builder_api_key
        self._builder_api_secret = builder_api_secret
        self._builder_passphrase = builder_passphrase
        self._host = host.rstrip("/")
        self._chain_id = int(chain_id)
        self._max_retries = max(1, int(max_retries))
        self._http = httpx.AsyncClient(
            base_url=self._host,
            timeout=timeout,
            transport=transport,
        )
        self._breaker = circuit_breaker or CircuitBreaker(name="clob-default")
        self._limiter = rate_limiter or RateLimiter(rps=0)

    # ----- public properties ----------------------------------------

    @property
    def address(self) -> str:
        return self._signer.address

    @property
    def funder(self) -> str:
        return self._funder

    @property
    def signature_type(self) -> int:
        return self._signature_type

    @property
    def has_builder_credentials(self) -> bool:
        return all(
            (
                self._builder_api_key,
                self._builder_api_secret,
                self._builder_passphrase,
            )
        )

    @property
    def circuit_breaker(self) -> CircuitBreaker:
        return self._breaker

    @property
    def rate_limiter(self) -> RateLimiter:
        return self._limiter

    # ----- lifecycle ------------------------------------------------

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "ClobAdapter":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    # ----- L1: credential lifecycle ---------------------------------

    async def derive_api_credentials(self, *, nonce: int = 0) -> dict:
        """``GET /auth/derive-api-key`` -- returns existing creds for this
        signer + nonce. The CLOB's idempotent recovery path; safe to call
        even when credentials already exist. Raises ``ClobAuthError`` on
        signature rejection.

        Not wrapped by the breaker -- credential derivation runs at boot
        and the operator wants the raw error if it fails.
        """
        headers = build_l1_headers(self._signer, nonce=nonce)
        await self._limiter.acquire()
        try:
            resp = await self._http.get(
                "/auth/derive-api-key", headers=dict(headers)
            )
        except httpx.TimeoutException as exc:
            raise ClobTimeoutError(
                f"timeout on /auth/derive-api-key: {exc}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ClobNetworkError(
                f"network error on /auth/derive-api-key: {exc}"
            ) from exc
        return self._parse(resp, path="/auth/derive-api-key")

    async def create_api_credentials(self, *, nonce: int = 0) -> dict:
        """``POST /auth/api-key`` -- generate fresh creds. Calling twice
        with the same nonce is rejected by the broker (use ``derive`` if
        you only need to recover existing creds).
        """
        headers = build_l1_headers(self._signer, nonce=nonce)
        await self._limiter.acquire()
        try:
            resp = await self._http.post(
                "/auth/api-key", headers=dict(headers)
            )
        except httpx.TimeoutException as exc:
            raise ClobTimeoutError(
                f"timeout on /auth/api-key: {exc}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ClobNetworkError(
                f"network error on /auth/api-key: {exc}"
            ) from exc
        return self._parse(resp, path="/auth/api-key")

    # ----- L2: order surface ----------------------------------------

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
        """Post a signed order.

        Wrapped by the circuit breaker -- consecutive transport failures
        trip the breaker so subsequent submissions short-circuit to
        ``ClobCircuitOpenError`` until the broker recovers.
        """
        signed = self._build_signed_order(
            token_id=token_id, side=side, price=price, size=size,
            tick_size=tick_size, neg_risk=neg_risk,
        )
        body = json.dumps(
            {"order": signed, "owner": self._api_key, "orderType": order_type},
            separators=(",", ":"),
        )
        return await self._breaker.call(
            lambda: self._signed_request("POST", "/order", body=body)
        )

    async def cancel_order(self, order_id: str) -> dict:
        body = json.dumps({"orderID": order_id}, separators=(",", ":"))
        return await self._breaker.call(
            lambda: self._signed_request("DELETE", "/order", body=body)
        )

    async def cancel_all_orders(self, market: Optional[str] = None) -> dict:
        """Cancel every open order, optionally scoped to a single market.

        Implementation note: the broker exposes two distinct endpoints --
        ``/cancel-market-orders`` (scoped) and ``/cancel-all`` (global).
        We keep the parameter optional so callers can express either
        intent without holding a reference to two different methods.
        """
        if market:
            body = json.dumps({"market": market}, separators=(",", ":"))
            return await self._signed_request(
                "DELETE", "/cancel-market-orders", body=body,
            )
        return await self._signed_request("DELETE", "/cancel-all", body="")

    async def cancel_all(self) -> dict:
        """Backwards-compatible alias for the global cancel path."""
        return await self.cancel_all_orders()

    async def get_order(self, order_id: str) -> dict:
        return await self._breaker.call(
            lambda: self._signed_request("GET", f"/data/order/{order_id}")
        )

    async def get_fills(
        self, order_id: str, *, market: Optional[str] = None,
    ) -> list[dict]:
        """Return broker-side fills associated with one order.

        Polymarket's ``/data/trades`` endpoint accepts ``id``,
        ``maker_address``, ``market``, ``asset_id``, ``before``,
        ``after`` (per the official ``py-clob-client.TradeParams`` /
        ``add_query_trade_params`` surface). It does NOT accept a
        ``taker_order_id`` filter -- supplying one either returns the
        full account history (which would corrupt downstream
        aggregation) or a 4xx -- so we query by ``maker_address``
        (always the signer) plus an optional ``market`` filter, and
        select trades client-side whose taker / maker order id matches
        ``order_id``.

        Maker-side trade rows nest the maker order hash inside
        ``maker_orders[].order_id`` rather than a top-level
        ``maker_order_id`` (see Polymarket Trade Object docs); we walk
        that array too so resting GTC/GTD fills aren't dropped (Codex
        P2 review).

        The wire shape can be either a bare list or a
        ``{"data": [...]}`` envelope depending on broker version -- we
        normalise to a list so callers always iterate uniformly.
        """
        path = f"/data/trades?maker_address={self._signer.address}"
        if market:
            path = f"{path}&market={market}"
        resp = await self._signed_request("GET", path)
        if isinstance(resp, list):
            trades = resp
        elif isinstance(resp, dict):
            data = resp.get("data")
            trades = list(data) if isinstance(data, list) else []
        else:
            trades = []
        return [t for t in trades if _trade_matches_order(t, order_id)]

    async def get_open_orders(
        self, market: Optional[str] = None,
    ) -> list[dict]:
        """Return open orders for the signed-in account, optionally
        scoped to a single market.
        """
        path = "/data/orders"
        if market:
            path = f"{path}?market={market}"
        resp = await self._signed_request("GET", path)
        if isinstance(resp, list):
            return resp
        data = resp.get("data") if isinstance(resp, dict) else None
        return list(data) if isinstance(data, list) else []

    async def request(
        self,
        method: str,
        path: str,
        *,
        body: str = "",
    ) -> dict:
        """Escape hatch for endpoints we have not modelled explicitly.

        Caller MUST pass the JSON body it intends to send (verbatim) so
        the HMAC over ``timestamp + method + path + body`` matches what
        the server will recompute. Passing a Python dict through ``json``
        and then a different ``json`` shape would break the signature.
        """
        return await self._signed_request(method.upper(), path, body=body)

    # ----- internals ------------------------------------------------

    def _build_signed_order(
        self,
        *,
        token_id: str,
        side: str,
        price: float,
        size: float,
        tick_size: Optional[str] = None,
        neg_risk: Optional[bool] = None,
    ) -> dict:
        """Delegate on-chain order signing to py-clob-client.OrderBuilder.

        Phase 4A scope owns the *transport* layer; the on-chain order
        schema (CTF Exchange EIP-712, salt, taker/maker addresses) stays
        on the proven SDK path until Phase 4C explicitly reimplements it.
        Importing locally keeps this adapter usable in unit tests that
        only exercise the auth + transport layers.

        ``tick_size`` and ``neg_risk`` are forwarded through
        ``CreateOrderOptions`` only when at least one is set; this keeps
        the default code-path identical to Phase 4A and avoids surfacing
        SDK-internal option objects to every caller.
        """
        try:
            from py_clob_client.clob_types import OrderArgs  # noqa: WPS433
            from py_clob_client.order_builder.builder import (  # noqa: WPS433
                OrderBuilder,
            )
            from py_clob_client.signer import Signer  # noqa: WPS433
        except Exception as exc:  # pragma: no cover - dep is in requirements
            raise ClobAuthError(
                f"py-clob-client required for order signing: {exc}"
            ) from exc

        signer = Signer(
            key=self._signer.private_key, chain_id=self._chain_id,
        )
        builder = OrderBuilder(signer, sig_type=self._signature_type, funder=self._funder)
        order_args = OrderArgs(
            token_id=token_id,
            price=price,
            size=size,
            side=side.upper(),
        )
        if tick_size is not None or neg_risk is not None:
            try:
                from py_clob_client.clob_types import (  # noqa: WPS433
                    CreateOrderOptions,
                )
            except Exception as exc:  # pragma: no cover - dep is in requirements
                raise ClobAuthError(
                    f"py-clob-client CreateOrderOptions unavailable: {exc}"
                ) from exc
            opts = CreateOrderOptions(
                tick_size=tick_size,
                neg_risk=bool(neg_risk) if neg_risk is not None else False,
            )
            signed = builder.create_order(order_args, opts)
        else:
            signed = builder.create_order(order_args)
        return signed.dict()

    async def _signed_request(
        self,
        method: str,
        path: str,
        *,
        body: str = "",
    ) -> dict:
        headers: dict[str, str] = dict(
            build_l2_headers(
                api_key=self._api_key,
                api_secret=self._api_secret,
                passphrase=self._passphrase,
                address=self._signer.address,
                method=method,
                path=path,
                body=body,
            )
        )
        if self.has_builder_credentials:
            headers.update(
                dict(
                    build_builder_headers(
                        builder_api_key=self._builder_api_key,  # type: ignore[arg-type]
                        builder_api_secret=self._builder_api_secret,  # type: ignore[arg-type]
                        builder_passphrase=self._builder_passphrase,  # type: ignore[arg-type]
                        method=method,
                        path=path,
                        body=body,
                    )
                )
            )
        if body:
            headers["Content-Type"] = "application/json"

        try:
            async for attempt in AsyncRetrying(
                reraise=True,
                stop=stop_after_attempt(self._max_retries),
                wait=wait_exponential(multiplier=1, min=1, max=8),
                retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            ):
                with attempt:
                    return await self._do_request(method, path, headers, body)
        except RETRYABLE_EXCEPTIONS as exc:
            raise ClobMaxRetriesError(
                f"max retries exceeded on {path}: {type(exc).__name__}: {exc}",
                last_exception=exc,
            ) from exc
        raise RuntimeError(  # pragma: no cover - tenacity always exits
            "ClobAdapter._signed_request: unreachable"
        )

    async def _do_request(
        self,
        method: str,
        path: str,
        headers: dict[str, str],
        body: str,
    ) -> dict:
        await self._limiter.acquire()
        try:
            resp = await self._http.request(
                method, path, headers=headers, content=body or None,
            )
        except httpx.TimeoutException as exc:
            raise ClobTimeoutError(
                f"timeout on {path}: {exc}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ClobNetworkError(
                f"network error on {path}: {exc}"
            ) from exc

        if 200 <= resp.status_code < 300:
            return self._parse(resp, path=path)

        # Non-2xx: classify into typed exception so the retry layer can
        # decide. Auth-class (400/401/403) and other 4xx propagate
        # immediately; 429 and 5xx-class are retried.
        raise _classify_http_error(
            resp.status_code, path=path, body=resp.text or "",
        )

    def _parse(self, resp: httpx.Response, *, path: str) -> dict:
        text = resp.text or ""
        if resp.status_code >= 400:
            # _do_request now classifies before reaching _parse, but the
            # L1 paths (derive_api_credentials / create_api_credentials)
            # call _parse directly to bypass the breaker -- keep the
            # legacy classification here so credential bootstrap still
            # raises typed errors.
            raise _classify_http_error(
                resp.status_code, path=path, body=text,
            )
        if not text:
            return {}
        try:
            return resp.json()
        except json.JSONDecodeError as exc:
            raise ClobAPIError(
                status_code=resp.status_code,
                path=path,
                body=text,
                message=f"CLOB returned non-JSON body on {path}: {exc}",
            ) from exc
