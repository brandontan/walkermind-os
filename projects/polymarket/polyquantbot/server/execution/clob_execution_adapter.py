"""Real CLOB execution adapter — guarded live order submission for CrusaderBot.

ClobExecutionAdapter is the sole real CLOB order-submission surface in the server
domain.  It is unconditionally guarded: every submission attempt passes through
LiveExecutionGuard before any network call is made.  If the guard blocks, the
adapter raises ClobSubmissionBlockedError and no order reaches the exchange.

Architecture:
  ClobExecutionAdapter
    ├── LiveExecutionGuard.check()  ← must pass first (all 5 gates)
    ├── ClobClientProtocol          ← injected; real or mocked
    │    └── post_order(payload)    ← network call only when guard passes
    └── OrderResultSchema           ← typed result returned to caller

Production use:
  From live_executor or an equivalent wired worker, inject a real
  AiohttpClobClient (or any ClobClientProtocol implementor) and a
  LiveExecutionGuard built from CapitalModeConfig.from_env().

  The guard enforces ENABLE_LIVE_TRADING + CAPITAL_MODE_CONFIRMED +
  RISK_CONTROLS_VALIDATED + EXECUTION_PATH_VALIDATED +
  SECURITY_HARDENING_VALIDATED before the adapter fires.

Paper-mode / test use:
  Inject a MockClobClient to exercise the full submission path (JSON
  building → guard → client call → result parsing) without any live
  network call or real fund movement.

Claim level: NARROW INTEGRATION
  This module provides a tested adapter path.  It does NOT set any
  gate env var.  EXECUTION_PATH_VALIDATED remains NOT SET until
  WARP•SENTINEL approves.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import structlog

from projects.polymarket.polyquantbot.server.config.capital_mode_config import CapitalModeConfig
from projects.polymarket.polyquantbot.server.core.live_execution_control import (
    LiveExecutionBlockedError,
    LiveExecutionGuard,
)
from projects.polymarket.polyquantbot.server.core.public_beta_state import PublicBetaState
from projects.polymarket.polyquantbot.server.integrations.falcon_gateway import CandidateSignal
from projects.polymarket.polyquantbot.server.risk.capital_risk_gate import WalletFinancialProvider

log = structlog.get_logger(__name__)

# ── Errors ────────────────────────────────────────────────────────────────────


class ClobSubmissionBlockedError(Exception):
    """Raised when guard blocks before any CLOB network call is made.

    Attributes:
        reason: Machine-readable block reason forwarded from LiveExecutionBlockedError.
    """

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(
            f"CLOB submission blocked [{reason}]: {detail}"
            if detail
            else f"CLOB submission blocked [{reason}]"
        )


class ClobSubmissionError(Exception):
    """Raised when the CLOB client returns an error response or raises."""

    def __init__(self, message: str, raw_response: dict[str, Any] | None = None) -> None:
        self.raw_response = raw_response
        super().__init__(message)


# ── CLOB Client protocol ───────────────────────────────────────────────────────


@runtime_checkable
class ClobClientProtocol(Protocol):
    """Protocol for CLOB order submission clients.

    Implementors must supply an async post_order() that accepts a
    structured order payload dict and returns the raw JSON response dict.

    Both real HTTP clients and mock test clients must satisfy this protocol.
    """

    async def post_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Submit an order payload to the CLOB.

        Args:
            payload: Structured order dict as required by the Polymarket CLOB API.
                     See https://docs.polymarket.com for full schema reference.

        Returns:
            Raw JSON response dict from the exchange.

        Raises:
            ClobSubmissionError: Network failure or error response.
        """
        ...


# ── Order result ──────────────────────────────────────────────────────────────


@dataclass
class ClobOrderResult:
    """Typed result of a successful (or simulated) CLOB order submission.

    Attributes:
        order_id:       Order ID returned by the CLOB (may be mock ID in tests).
        condition_id:   Polymarket condition ID of the market.
        token_id:       Token ID the order was placed on.
        side:           "BUY" or "SELL".
        size:           Order size in shares.
        price:          Limit price (0.0–1.0).
        status:         Raw status string from exchange (e.g. "MATCHED", "LIVE").
        mode:           "live" or "mocked" — set by adapter based on client type.
        dedup_key:      SHA-256 deduplication key used for this order.
        submitted_at_ns: Unix nanoseconds at submission time.
    """

    order_id: str
    condition_id: str
    token_id: str
    side: str
    size: float
    price: float
    status: str
    mode: str
    dedup_key: str
    submitted_at_ns: int


# ── Deduplication helper ───────────────────────────────────────────────────────


def _build_dedup_key(condition_id: str, token_id: str, side: str, price: float, size: float) -> str:
    """Build a deterministic dedup key from order identity fields.

    Args:
        condition_id: Polymarket condition ID.
        token_id:     Polymarket token ID.
        side:         "BUY" or "SELL".
        price:        Limit price.
        size:         Order size.

    Returns:
        16-character hex prefix of SHA-256 hash of the canonical key string.
    """
    key = f"{condition_id}:{token_id}:{side}:{price:.6f}:{size:.6f}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


# ── Order payload builder ──────────────────────────────────────────────────────


def build_order_payload(
    signal: CandidateSignal,
    token_id: str,
    order_type: str = "GTC",
    fee_rate_bps: int = 0,
) -> dict[str, Any]:
    """Build a structured CLOB order payload from a CandidateSignal.

    This function constructs the payload dict that ClobClientProtocol.post_order()
    expects.  The caller is responsible for signing and injecting auth fields
    before sending to a live exchange.

    Args:
        signal:        CandidateSignal with price, size, side, condition_id, signal_id.
        token_id:      Polymarket token ID for this outcome (YES/NO token).
        order_type:    "GTC" (Good-Till-Cancelled), "FOK", or "FAK". Default "GTC".
        fee_rate_bps:  Fee rate in basis points. Default 0.

    Returns:
        Order payload dict ready for ClobClientProtocol.post_order().
    """
    side = str(getattr(signal, "side", "BUY")).upper()
    price = float(getattr(signal, "price", 0.5))
    size = float(getattr(signal, "size", 0.0))
    condition_id = str(getattr(signal, "condition_id", ""))

    # Polymarket CLOB uses USDC with 6 decimals for maker_amount
    maker_amount_usdc = int(round(price * size * 1_000_000))
    taker_amount_shares = int(round(size * 1_000_000))

    return {
        "order": {
            "salt": int(time.time() * 1000),
            "tokenId": token_id,
            "makerAmount": str(maker_amount_usdc),
            "takerAmount": str(taker_amount_shares),
            "side": side,
            "feeRateBps": str(fee_rate_bps),
            "expiration": "0",
            "nonce": "0",
            "signatureType": 0,
        },
        "orderType": order_type,
        "_meta": {
            "condition_id": condition_id,
            "signal_id": str(getattr(signal, "signal_id", "")),
            "price": price,
            "size": size,
        },
    }


# ── Adapter ───────────────────────────────────────────────────────────────────


class ClobExecutionAdapter:
    """Guarded real CLOB execution adapter for live order submission.

    Every order attempt passes through LiveExecutionGuard before any
    network call.  If the guard blocks (kill_switch, mode != live,
    env vars not set, capital gates off), ClobSubmissionBlockedError is raised
    and the client is never called.

    Args:
        config:    CapitalModeConfig — supplies gate state.
        client:    ClobClientProtocol — real HTTP client or mock.
        mode:      Label injected into ClobOrderResult ("live" or "mocked").
                   Callers set this explicitly to track test vs. real submissions.
    """

    def __init__(
        self,
        config: CapitalModeConfig,
        client: ClobClientProtocol,
        mode: str = "live",
    ) -> None:
        self._config = config
        self._client = client
        self._mode = mode
        self._guard = LiveExecutionGuard(config=config)

    async def submit_order(
        self,
        state: PublicBetaState,
        signal: CandidateSignal,
        token_id: str,
        provider: WalletFinancialProvider | None = None,
        wallet_id: str = "__adapter_probe__",
        order_type: str = "GTC",
    ) -> ClobOrderResult:
        """Submit a live order to the CLOB after guard validation.

        Guard chain (in order):
          1. LiveExecutionGuard.check() — all 5 capital gates + provider
          2. Payload construction via build_order_payload()
          3. Dedup key generation
          4. client.post_order(payload) — network call only when guard passes
          5. Result parsing into ClobOrderResult

        Args:
            state:      Live PublicBetaState.
            signal:     CandidateSignal — source of price, size, side, condition_id.
            token_id:   Polymarket token ID (YES/NO outcome token).
            provider:   WalletFinancialProvider — required for live guard check.
            wallet_id:  Wallet ID for provider probe.
            order_type: CLOB order type — "GTC", "FOK", or "FAK".

        Returns:
            ClobOrderResult with submission details.

        Raises:
            ClobSubmissionBlockedError: Guard blocks before any network call.
            ClobSubmissionError:         Client call fails or returns error response.
        """
        # Guard: must pass before any network activity
        try:
            self._guard.check(state, provider=provider, wallet_id=wallet_id)
        except LiveExecutionBlockedError as exc:
            log.warning(
                "clob_adapter_submission_blocked",
                reason=exc.reason,
                detail=exc.detail,
                signal_id=getattr(signal, "signal_id", None),
                mode=self._mode,
            )
            raise ClobSubmissionBlockedError(reason=exc.reason, detail=exc.detail) from exc

        # Build payload
        payload = build_order_payload(signal=signal, token_id=token_id, order_type=order_type)
        condition_id = str(getattr(signal, "condition_id", ""))
        side = str(getattr(signal, "side", "BUY")).upper()
        price = float(getattr(signal, "price", 0.5))
        size = float(getattr(signal, "size", 0.0))
        dedup_key = _build_dedup_key(condition_id, token_id, side, price, size)

        log.info(
            "clob_adapter_submitting_order",
            condition_id=condition_id,
            token_id=token_id,
            side=side,
            price=price,
            size=size,
            order_type=order_type,
            dedup_key=dedup_key,
            mode=self._mode,
        )

        submitted_at_ns = time.time_ns()
        try:
            raw_response = await self._client.post_order(payload)
        except Exception as exc:
            log.error(
                "clob_adapter_client_error",
                error=str(exc),
                condition_id=condition_id,
                dedup_key=dedup_key,
                mode=self._mode,
            )
            raise ClobSubmissionError(
                f"CLOB client raised during post_order: {exc}",
                raw_response=None,
            ) from exc

        # Validate response shape
        if not isinstance(raw_response, dict):
            raise ClobSubmissionError(
                f"CLOB client returned non-dict response: {type(raw_response).__name__}",
                raw_response=None,
            )

        order_id = str(raw_response.get("orderId", raw_response.get("order_id", dedup_key)))
        status = str(raw_response.get("status", "UNKNOWN"))

        result = ClobOrderResult(
            order_id=order_id,
            condition_id=condition_id,
            token_id=token_id,
            side=side,
            size=size,
            price=price,
            status=status,
            mode=self._mode,
            dedup_key=dedup_key,
            submitted_at_ns=submitted_at_ns,
        )

        log.info(
            "clob_adapter_order_submitted",
            order_id=order_id,
            condition_id=condition_id,
            status=status,
            dedup_key=dedup_key,
            mode=self._mode,
            elapsed_ns=time.time_ns() - submitted_at_ns,
        )
        return result
