"""Chainlink BTC/USD Data Streams oracle client.

Reads the **same source the Polymarket BTC up/down candle markets resolve
against** — the Chainlink BTC/USD Data Stream (``data.chain.link/streams/
btc-usd``) — via the pull-based Data Streams REST API. The market basis is
decided in the final seconds against this exact stream, so spot proxies
(Binance/Coinbase) are deliberately NOT used here.

Foundation layer (WARP-62, Chunk 1/4): this module ONLY reads the live price
and exposes it. It does NOT compute fair value or wire into any strategy —
that is Chunk 3. The runtime entrypoints are gated behind the
``ORACLE_ENABLED`` feature flag (default OFF), and credentials live in ``.env``
only (never hardcoded).

Data Streams REST contract (https://docs.chain.link/data-streams):
  * ``GET /api/v1/reports/latest?feedID={feedID}``
  * HMAC-SHA256 auth over ``"{method} {path} {sha256(body)} {clientId}
    {timestampMs}"`` using the API secret; headers ``Authorization`` /
    ``X-Authorization-Timestamp`` / ``X-Authorization-Signature-SHA256``.
  * Response ``{"report": {"feedID", "validFromTimestamp",
    "observationsTimestamp", "fullReport"}}`` where ``fullReport`` is an
    ABI-encoded envelope wrapping the report blob. The v3 (crypto) blob carries
    the benchmark ``price`` as ``int192`` scaled by 1e18.

No silent failures: every external error is logged (structured) and surfaces as
a typed ``OracleError``. The client NEVER fabricates a price — an unavailable or
undecodable report raises rather than returning a placeholder.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any, Awaitable, Callable, Optional

import httpx
import structlog
from eth_abi import decode as abi_decode
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ....config import get_settings

log = structlog.get_logger(__name__)

# Benchmark price scaling for Chainlink Data Streams crypto (v3) reports.
_PRICE_SCALE = 10**18

# ABI layout of the Data Streams ``fullReport`` envelope. The report blob is the
# second member; the signatures are not needed for a read-only price.
_ENVELOPE_ABI: tuple[str, ...] = (
    "bytes32[3]",  # reportContext
    "bytes",       # reportBlob  <- what we decode next
    "bytes32[]",   # rawRs
    "bytes32[]",   # rawSs
    "bytes32",     # rawVs
)

# ABI layout of the v3 (crypto) report blob. ``price`` (index 6) is the
# benchmark used for resolution.
_REPORT_V3_ABI: tuple[str, ...] = (
    "bytes32",  # feedId
    "uint32",   # validFromTimestamp
    "uint32",   # observationsTimestamp
    "uint192",  # nativeFee
    "uint192",  # linkFee
    "uint32",   # expiresAt
    "int192",   # price  <- benchmark
    "int192",   # bid
    "int192",   # ask
)
_REPORT_V3_PRICE_INDEX = 6


# A transport is an async callable that performs one signed GET and returns the
# decoded JSON body. The default httpx-backed implementation is injected at
# construction; tests pass a stub so no network is touched.
Transport = Callable[[str, dict[str, str], float], Awaitable[Any]]


class OracleError(RuntimeError):
    """Base class for all oracle failures (no silent fallback)."""


class OracleDisabledError(OracleError):
    """Raised when a runtime entrypoint is used while ORACLE_ENABLED is OFF."""


class OracleConfigError(OracleError):
    """Raised when required oracle credentials/knobs are missing."""


class OracleUnavailableError(OracleError):
    """Raised when the report cannot be fetched or decoded into a price."""


def _now_ms() -> int:
    """Wall-clock milliseconds. Seam — tests monkeypatch for a fixed clock."""
    return int(time.time() * 1000)


def build_hmac_signature(
    *,
    method: str,
    path: str,
    body: bytes,
    api_key: str,
    api_secret: str,
    timestamp_ms: int,
) -> str:
    """Compute the Data Streams HMAC-SHA256 signature (hex).

    Matches the Chainlink reference: the signed string is
    ``"{METHOD} {path} {sha256(body)} {apiKey} {timestampMs}"`` and the digest
    is keyed by the API secret. ``path`` MUST include the query string exactly
    as sent, or the server rejects the signature.
    """
    body_hash = hashlib.sha256(body).hexdigest()
    message = f"{method.upper()} {path} {body_hash} {api_key} {int(timestamp_ms)}"
    return hmac.new(
        api_secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def decode_benchmark_price(full_report_hex: str) -> float:
    """Decode the benchmark BTC/USD price (USD float) from a ``fullReport`` hex.

    Unwraps the ABI envelope to the report blob, then decodes the v3 crypto
    layout and rescales the ``int192`` benchmark from 1e18 fixed-point. Raises
    ``OracleUnavailableError`` on any malformed payload — never returns a guess.
    """
    raw = full_report_hex[2:] if full_report_hex.startswith("0x") else full_report_hex
    try:
        report_bytes = bytes.fromhex(raw)
    except ValueError as exc:
        raise OracleUnavailableError(f"fullReport is not valid hex: {exc}") from exc
    try:
        _ctx, report_blob, *_sigs = abi_decode(list(_ENVELOPE_ABI), report_bytes)
        decoded = abi_decode(list(_REPORT_V3_ABI), report_blob)
        raw_price = int(decoded[_REPORT_V3_PRICE_INDEX])
    except Exception as exc:  # eth_abi raises a family of decode errors
        raise OracleUnavailableError(
            f"fullReport ABI decode failed: {exc}"
        ) from exc
    if raw_price <= 0:
        raise OracleUnavailableError(f"non-positive benchmark price: {raw_price}")
    return raw_price / _PRICE_SCALE


def _default_transport() -> Transport:
    """httpx-backed transport with retry + backoff on transient HTTP errors."""

    def _retry() -> AsyncRetrying:
        return AsyncRetrying(
            reraise=True,
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=8),
            retry=retry_if_exception_type(
                (httpx.HTTPError, httpx.TimeoutException)
            ),
        )

    async def _transport(url: str, headers: dict[str, str], timeout: float) -> Any:
        async for attempt in _retry():
            with attempt:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.get(url, headers=headers)
                    resp.raise_for_status()
                    return resp.json()
        # AsyncRetrying(reraise=True) re-raises on exhaustion, so this is
        # unreachable; kept explicit so no path returns None silently.
        raise OracleUnavailableError("transport retry exhausted")

    return _transport


class ChainlinkDataStreamsClient:
    """Async, pull-based client for the Chainlink BTC/USD Data Stream.

    Construct directly with explicit credentials (tests inject a stub
    ``transport``), or use :func:`get_btc_price` for the settings-driven,
    flag-gated runtime entrypoint.
    """

    _REPORT_PATH = "/api/v1/reports/latest"

    def __init__(
        self,
        *,
        api_url: str,
        api_key: str,
        api_secret: str,
        feed_id: str,
        timeout: float = 5.0,
        transport: Optional[Transport] = None,
    ) -> None:
        if not (api_key and api_secret):
            raise OracleConfigError("Chainlink Data Streams credentials missing")
        if not feed_id:
            raise OracleConfigError("Chainlink BTC/USD feed_id missing")
        self._api_url = api_url.rstrip("/")
        self._api_key = api_key
        self._api_secret = api_secret
        self._feed_id = feed_id
        self._timeout = timeout
        self._transport = transport or _default_transport()

    def _signed_request(self) -> tuple[str, dict[str, str]]:
        """Build the (url, headers) for the latest-report GET."""
        path = f"{self._REPORT_PATH}?feedID={self._feed_id}"
        ts_ms = _now_ms()
        signature = build_hmac_signature(
            method="GET",
            path=path,
            body=b"",
            api_key=self._api_key,
            api_secret=self._api_secret,
            timestamp_ms=ts_ms,
        )
        headers = {
            "Authorization": self._api_key,
            "X-Authorization-Timestamp": str(ts_ms),
            "X-Authorization-Signature-SHA256": signature,
        }
        return f"{self._api_url}{path}", headers

    async def fetch_latest_report(self) -> dict[str, Any]:
        """Fetch the raw latest report dict for the BTC/USD feed.

        Raises ``OracleUnavailableError`` on transport failure or a response
        shape that carries no ``fullReport``.
        """
        url, headers = self._signed_request()
        try:
            payload = await self._transport(url, headers, self._timeout)
        except OracleError:
            raise
        except Exception as exc:
            log.warning(
                "chainlink datastreams fetch failed",
                feed_id=self._feed_id,
                err=str(exc),
            )
            raise OracleUnavailableError(
                f"Chainlink Data Streams fetch failed: {exc}"
            ) from exc
        report = (payload or {}).get("report") if isinstance(payload, dict) else None
        if not isinstance(report, dict) or not report.get("fullReport"):
            log.warning(
                "chainlink datastreams response missing fullReport",
                feed_id=self._feed_id,
            )
            raise OracleUnavailableError("Data Streams response missing fullReport")
        return report

    async def get_btc_price(self) -> float:
        """Return the live Chainlink BTC/USD benchmark price as a USD float."""
        report = await self.fetch_latest_report()
        price = decode_benchmark_price(str(report["fullReport"]))
        log.info(
            "chainlink btc/usd price read",
            feed_id=self._feed_id,
            price=price,
            observations_ts=report.get("observationsTimestamp"),
        )
        return price


def client_from_settings(
    *, transport: Optional[Transport] = None
) -> ChainlinkDataStreamsClient:
    """Build a client from Settings + ``.env`` credentials.

    Honours the ``ORACLE_ENABLED`` feature flag (default OFF): the runtime
    entrypoint refuses to read the oracle until the operator opts in. Tests that
    want to exercise decoding/transport construct the client directly instead.
    """
    settings = get_settings()
    if not getattr(settings, "ORACLE_ENABLED", False):
        raise OracleDisabledError("ORACLE_ENABLED is OFF")
    api_key = getattr(settings, "CHAINLINK_DATASTREAMS_API_KEY", None)
    api_secret = getattr(settings, "CHAINLINK_DATASTREAMS_API_SECRET", None)
    if not (api_key and api_secret):
        raise OracleConfigError(
            "CHAINLINK_DATASTREAMS_API_KEY / _API_SECRET not set in .env"
        )
    return ChainlinkDataStreamsClient(
        api_url=settings.ORACLE_CHAINLINK_API_URL,
        api_key=api_key,
        api_secret=api_secret,
        feed_id=settings.ORACLE_CHAINLINK_BTC_FEED_ID,
        timeout=settings.ORACLE_TIMEOUT_SEC,
        transport=transport,
    )


async def get_btc_price() -> float:
    """Runtime entrypoint — live Chainlink BTC/USD price (USD float).

    Flag-gated via ``ORACLE_ENABLED``; raises ``OracleDisabledError`` when OFF.
    """
    return await client_from_settings().get_btc_price()
