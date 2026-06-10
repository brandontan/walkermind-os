"""Rust order-sidecar CLOB backend — deposit-wallet (POLY_1271) orders.

WHY: Polymarket migrated Magic/email accounts to EIP-7702 deposit wallets;
py-clob-client-v2 cannot sign orders for them (upstream #52/#53/#64/#70/#71,
all OPEN). The official Rust SDK's canary line is the only client carrying
``SignatureType::Poly1271`` + the wrapped EIP-1271 order signature. The
``sidecar/`` crate in this project wraps that capability behind a one-shot
JSON-over-stdio protocol; this module is the Python side.

Selected by ``USE_RUST_SIDECAR`` in ``get_clob_client`` (precedence over
``USE_CLOB_V2`` / ``USE_PYSDK_CLOB``; default OFF). Implements the same
``ClobClientProtocol`` as every other backend — callers are unchanged.

Process model: ONE subprocess per call, stateless. No long-lived sidecar
daemon — a crash cannot leave a zombie order loop, and the bot's existing
breaker + limiter wrap each invocation exactly like an HTTP call. Subprocess
spawn cost (~10ms) is noise against the broker round-trip (~300ms).

Secrets: the private key + L2 creds travel via the child's environment —
NEVER argv (argv is world-readable in /proc). Stdout carries only the JSON
result; the sidecar never prints secret material.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Optional

from .circuit_breaker import CircuitBreaker
from .exceptions import ClobAPIError, ClobConfigError, ClobError, ClobNetworkError
from .rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

__all__ = ["RustSidecarClient", "DEFAULT_SIDECAR_TIMEOUT_SEC"]

# Generous per-invocation wall clock: spawn + L1/L2 auth + broker round-trip.
# A hung sidecar is killed at the deadline — the breaker records the failure.
DEFAULT_SIDECAR_TIMEOUT_SEC = 45.0

_SUPPORTED_ORDER_TYPES = {"GTC", "FOK", "FAK"}


class RustSidecarClient:
    """``ClobClientProtocol`` implementation backed by the Rust order sidecar."""

    def __init__(
        self,
        *,
        binary_path: str,
        private_key: str,
        funder_address: str,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        passphrase: Optional[str] = None,
        clob_url: Optional[str] = None,
        circuit_breaker: Optional[CircuitBreaker] = None,
        rate_limiter: Optional[RateLimiter] = None,
        timeout_sec: float = DEFAULT_SIDECAR_TIMEOUT_SEC,
    ) -> None:
        if not binary_path:
            raise ClobConfigError("rust sidecar: binary_path is required")
        if not private_key:
            raise ClobConfigError("rust sidecar: private_key is required")
        if not funder_address:
            raise ClobConfigError(
                "rust sidecar: funder_address (deposit wallet) is required — "
                "POLY_1271 orders have no EOA fallback"
            )
        self._binary_path = binary_path
        self._private_key = private_key
        self._funder = funder_address
        self._api_key = api_key
        self._api_secret = api_secret
        self._passphrase = passphrase
        self._clob_url = clob_url
        self._breaker = circuit_breaker or CircuitBreaker(name="clob-rust-sidecar")
        self._limiter = rate_limiter or RateLimiter(rps=0)
        self._timeout_sec = float(timeout_sec)

    # ----- invocation core ------------------------------------------------

    def _child_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["SIDECAR_PRIVATE_KEY"] = self._private_key
        env["SIDECAR_FUNDER"] = self._funder
        if self._clob_url:
            env["SIDECAR_CLOB_URL"] = self._clob_url
        if self._api_key and self._api_secret and self._passphrase:
            env["SIDECAR_API_KEY"] = self._api_key
            env["SIDECAR_API_SECRET"] = self._api_secret
            env["SIDECAR_PASSPHRASE"] = self._passphrase
        return env

    async def _invoke(self, action: str, params: Optional[dict] = None) -> Any:
        """Run one sidecar invocation. Returns the ``result`` payload.

        Raises:
            ClobNetworkError: spawn failure, timeout, non-zero exit, bad JSON.
            ClobAPIError: the sidecar reported an action-level failure
                (broker rejection, auth refusal) — ``ok=false`` with exit 0.
        """
        request = json.dumps({"action": action, "params": params or {}})
        try:
            proc = await asyncio.create_subprocess_exec(
                self._binary_path,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._child_env(),
            )
        except FileNotFoundError as exc:
            raise ClobConfigError(
                f"rust sidecar binary not found at {self._binary_path!r} — "
                "build it (cargo build --release) or fix RUST_SIDECAR_PATH"
            ) from exc
        except OSError as exc:
            raise ClobNetworkError(f"rust sidecar spawn failed: {exc}") from exc

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(request.encode()),
                timeout=self._timeout_sec,
            )
        except asyncio.TimeoutError as exc:
            proc.kill()
            # Reap the killed child so no zombie lingers; best effort.
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.error("rust sidecar: kill did not reap within 5s")
            raise ClobNetworkError(
                f"rust sidecar timed out after {self._timeout_sec}s on {action}"
            ) from exc

        if proc.returncode not in (0,):
            # Exit 2 = protocol error (our bug, not the broker). Anything else
            # is an abnormal death (OOM, signal). Both are infra-shaped.
            raise ClobNetworkError(
                f"rust sidecar exited {proc.returncode} on {action}: "
                f"{stderr.decode(errors='replace')[:300]}"
            )

        try:
            payload = json.loads(stdout.decode())
        except (ValueError, UnicodeDecodeError) as exc:
            raise ClobNetworkError(
                f"rust sidecar emitted invalid JSON on {action}: "
                f"{stdout[:200]!r}"
            ) from exc

        if not payload.get("ok"):
            # Action-level failure — broker said no / auth refused / bad params.
            # Surface as an API error so callers' existing classification
            # (retryable vs config) applies.
            raise ClobAPIError(
                status_code=0,
                path=f"sidecar:{action}",
                body=str(payload.get("error", "")),
                message=f"rust sidecar {action} failed: {payload.get('error')}",
            )
        return payload.get("result")

    # ----- ClobClientProtocol ----------------------------------------------

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
            raise ClobConfigError(
                f"rust sidecar backend: order_type {ot!r} unsupported "
                f"(supported: {sorted(_SUPPORTED_ORDER_TYPES)})"
            )
        # tick_size / neg_risk are resolved server-side by the SDK's order
        # builder (it fetches the market's tick size); the explicit overrides
        # the Protocol carries are advisory for this backend.
        params = {
            "token_id": str(token_id),
            "side": side.upper(),
            # Decimal strings — the sidecar parses with rust_decimal; floats
            # would re-introduce binary-float dust into price/size.
            "price": _decimal_str(price),
            "size": _decimal_str(size),
            "order_type": ot,
        }

        async def _do() -> dict:
            await self._limiter.acquire()
            result = await self._invoke("place_order", params)
            return dict(result)

        return await self._breaker.call(_do)

    async def cancel_order(self, order_id: str) -> dict:
        async def _do() -> dict:
            await self._limiter.acquire()
            result = await self._invoke("cancel_order", {"order_id": order_id})
            return dict(result)

        return await self._breaker.call(_do)

    async def cancel_all_orders(self, market: Optional[str] = None) -> dict:
        # The sidecar's cancel_all is account-wide; a market-scoped cancel is
        # a follow-up (SDK supports cancel_market_orders). Fail loudly rather
        # than silently cancelling MORE than the caller asked for.
        if market:
            raise ClobConfigError(
                "rust sidecar backend: market-scoped cancel_all not yet "
                "supported — call with market=None (account-wide) or use "
                "cancel_order per id"
            )

        async def _do() -> dict:
            await self._limiter.acquire()
            result = await self._invoke("cancel_all", {})
            return dict(result)

        return await self._breaker.call(_do)

    async def get_order(self, order_id: str) -> dict:
        async def _do() -> dict:
            await self._limiter.acquire()
            result = await self._invoke("get_order", {"order_id": order_id})
            return dict(result)

        return await self._breaker.call(_do)

    async def get_fills(self, order_id: str) -> list[dict]:
        async def _do() -> list[dict]:
            await self._limiter.acquire()
            result = await self._invoke("get_trades", {"order_id": order_id})
            return list(result.get("trades", []))

        return await self._breaker.call(_do)

    async def get_open_orders(self, market: Optional[str] = None) -> list[dict]:
        async def _do() -> list[dict]:
            await self._limiter.acquire()
            result = await self._invoke("get_open_orders", {})
            orders = list(result.get("orders", []))
            if market:
                orders = [o for o in orders if o.get("market") == market]
            return orders

        return await self._breaker.call(_do)

    async def aclose(self) -> None:
        """Stateless backend — nothing to close (one subprocess per call)."""
        return None


def _decimal_str(value: float) -> str:
    """Render a float as a short decimal string without binary dust.

    ``repr(0.1 + 0.2)`` style artifacts must not reach the broker; format
    through a 6-dp quantize (Polymarket prices tick at 0.001 / sizes at
    0.01 — 6 dp is comfortably finer) then strip trailing zeros.
    """
    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return text or "0"
