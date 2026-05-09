"""ClobAdapter — REST client wrapping Polymarket CLOB authenticated endpoints.

This adapter is the Phase 4A replacement path for ``py-clob-client`` in
the live execution lane. It is intentionally minimal: only the surface
the live engine will need (post / cancel / get order, derive credentials)
plus a thin escape hatch (``request``) for future endpoints.

Hard rules respected:
  * No silent failures — every non-2xx HTTP response raises ``ClobAPIError``.
  * Exponential backoff via tenacity on transient HTTP errors only;
    auth-class errors (4xx) are NOT retried (re-signing wouldn't help and
    a duplicate POST after broker accept is a capital-safety footgun).
  * Async-only — no blocking I/O on the trading loop.
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
from .exceptions import ClobAPIError, ClobAuthError

logger = logging.getLogger(__name__)

DEFAULT_HOST = "https://clob.polymarket.com"
DEFAULT_TIMEOUT = 10.0


class ClobAdapter:
    """REST client for Polymarket CLOB authenticated endpoints.

    Attributes are kept private (single underscore) — the public surface
    is the async methods. Tests construct with an injected ``transport``
    via ``httpx.MockTransport`` to avoid network I/O.
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
        self._http = httpx.AsyncClient(
            base_url=self._host,
            timeout=timeout,
            transport=transport,
        )

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

    # ----- lifecycle ------------------------------------------------

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "ClobAdapter":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    # ----- L1: credential lifecycle ---------------------------------

    async def derive_api_credentials(self, *, nonce: int = 0) -> dict:
        """``GET /auth/derive-api-key`` — returns existing creds for this
        signer + nonce. The CLOB's idempotent recovery path; safe to call
        even when credentials already exist. Raises ``ClobAuthError`` on
        signature rejection.
        """
        headers = build_l1_headers(self._signer, nonce=nonce)
        resp = await self._http.get(
            "/auth/derive-api-key", headers=dict(headers)
        )
        return self._parse(resp, path="/auth/derive-api-key")

    async def create_api_credentials(self, *, nonce: int = 0) -> dict:
        """``POST /auth/api-key`` — generate fresh creds. Calling twice
        with the same nonce is rejected by the broker (use ``derive`` if
        you only need to recover existing creds).
        """
        headers = build_l1_headers(self._signer, nonce=nonce)
        resp = await self._http.post(
            "/auth/api-key", headers=dict(headers)
        )
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

        Construction of the on-chain ``signed_order`` blob (CTF Exchange
        EIP-712) is delegated to ``py-clob-client.OrderBuilder`` to avoid
        re-implementing the on-chain order schema in this adapter. We
        wrap the network leg ourselves so the L2 + builder header path
        is fully owned by Phase 4A.

        ``tick_size`` and ``neg_risk`` are threaded into
        ``OrderBuilder.create_order`` via ``CreateOrderOptions`` so
        callers can submit on neg-risk markets / non-default tick sizes
        without re-fetching market metadata on every submit.

        The OrderBuilder import is local to keep the module importable
        in environments where ``py-clob-client`` is not installed (CI
        smoke tests on machines without on-chain deps).
        """
        signed = self._build_signed_order(
            token_id=token_id, side=side, price=price, size=size,
            tick_size=tick_size, neg_risk=neg_risk,
        )
        body = json.dumps(
            {"order": signed, "owner": self._api_key, "orderType": order_type},
            separators=(",", ":"),
        )
        return await self._signed_request("POST", "/order", body=body)

    async def cancel_order(self, order_id: str) -> dict:
        body = json.dumps({"orderID": order_id}, separators=(",", ":"))
        return await self._signed_request("DELETE", "/order", body=body)

    async def cancel_all_orders(self, market: Optional[str] = None) -> dict:
        """Cancel every open order, optionally scoped to a single market.

        Implementation note: the broker exposes two distinct endpoints —
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
        return await self._signed_request("GET", f"/data/order/{order_id}")

    async def get_fills(
        self, order_id: str, *, market: Optional[str] = None,
    ) -> list[dict]:
        """Return broker-side fills associated with one order.

        Polymarket's ``/data/trades`` endpoint accepts ``id``,
        ``maker_address``, ``market``, ``asset_id``, ``before``,
        ``after`` (per the official ``py-clob-client.TradeParams`` /
        ``add_query_trade_params`` surface). It does NOT accept a
        ``taker_order_id`` filter — supplying one either returns the
        full account history (which would corrupt downstream
        aggregation) or a 4xx — so we query by ``maker_address``
        (always the signer) plus an optional ``market`` filter, and
        select trades client-side whose taker / maker order id matches
        ``order_id``.

        The wire shape can be either a bare list or a
        ``{"data": [...]}`` envelope depending on broker version — we
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
        return [
            t for t in trades
            if t.get("taker_order_id") == order_id
            or t.get("maker_order_id") == order_id
            or t.get("order_id") == order_id
            or t.get("orderID") == order_id
        ]

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

        async for attempt in AsyncRetrying(
            reraise=True,
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=8),
            retry=retry_if_exception_type(
                (httpx.HTTPError, httpx.TimeoutException)
            ),
        ):
            with attempt:
                resp = await self._http.request(
                    method, path, headers=headers, content=body or None,
                )
                # 4xx is auth/business-class — do NOT retry. Surface to
                # caller so duplicate POSTs after a broker accept never
                # happen on a stale signature.
                if 400 <= resp.status_code < 500:
                    return self._parse(resp, path=path)
                resp.raise_for_status()
                return self._parse(resp, path=path)
        raise RuntimeError("ClobAdapter._signed_request: unreachable")  # pragma: no cover

    def _parse(self, resp: httpx.Response, *, path: str) -> dict:
        text = resp.text or ""
        if resp.status_code >= 400:
            if resp.status_code in (401, 403):
                raise ClobAuthError(
                    f"CLOB rejected auth on {path}: "
                    f"{resp.status_code} {text[:200]}"
                )
            raise ClobAPIError(
                status_code=resp.status_code,
                path=path,
                body=text,
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
