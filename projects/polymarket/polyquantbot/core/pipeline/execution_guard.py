"""Phase 10 — ExecutionGuard: Pre-trade validation before order submission.

Performs a synchronous multi-point validation sweep before any order is
forwarded to the live executor.  A trade is rejected if ANY single check
fails.

Checks performed (in order)::

    1. Liquidity     — orderbook depth >= min_liquidity_usd (default $10k).
    2. Slippage      — estimated slippage <= max_slippage_pct (default 3%).
    3. Position size — size_usd <= max_position_usd (default 10% bankroll).
    4. Duplicate     — no open order with the same (market, side, price, size).

Integration point::

    guard = ExecutionGuard.from_config(config, order_guard=order_guard)
    result = guard.validate(
        market_id="0xabc",
        side="YES",
        price=0.62,
        size=100.0,
        liquidity_usd=15_000.0,
        slippage_pct=0.01,
        order_guard_signature="0xabc:YES:0.62:100.0",
    )
    if not result.passed:
        log.warning("trade_rejected", reason=result.reason)
        return

Thread-safety: single asyncio event loop (no mutation of shared state).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import structlog

log = structlog.get_logger()

# ── Defaults ──────────────────────────────────────────────────────────────────

_MIN_LIQUIDITY_USD: float = 10_000.0   # minimum orderbook depth
_MAX_SLIPPAGE_PCT: float = 0.03        # 3% max estimated slippage
_MAX_POSITION_USD: float = 1_000.0    # per-trade position cap (override via config)


# ── Validation result ─────────────────────────────────────────────────────────


@dataclass
class ValidationResult:
    """Result of an ExecutionGuard validation sweep.

    Attributes:
        passed: True if all checks pass.
        reason: Machine-readable reason for rejection (empty string on pass).
        checks: Per-check pass/fail detail dict.
    """

    passed: bool
    reason: str
    checks: dict


# ── ExecutionGuard ────────────────────────────────────────────────────────────


class ExecutionGuard:
    """Pre-trade validation gate for execution safety.

    All checks are synchronous and stateless (they do not mutate the guard).
    The optional ``order_guard`` reference is used only for read-only duplicate
    detection (checking whether a signature is already active).

    Raises no exceptions — all failures are returned as :class:`ValidationResult`
    with ``passed=False`` and a descriptive ``reason``.
    """

    def __init__(
        self,
        min_liquidity_usd: float = _MIN_LIQUIDITY_USD,
        max_slippage_pct: float = _MAX_SLIPPAGE_PCT,
        max_position_usd: float = _MAX_POSITION_USD,
        order_guard: Optional[object] = None,
    ) -> None:
        """Initialise the guard.

        Args:
            min_liquidity_usd: Minimum market liquidity required to trade.
            max_slippage_pct: Maximum acceptable estimated slippage (fraction).
            max_position_usd: Maximum allowed position size in USD.
            order_guard: Optional :class:`phase8.order_guard.OrderGuard` for
                         duplicate detection.  Pass ``None`` to skip that check.
        """
        self._min_liquidity_usd = min_liquidity_usd
        self._max_slippage_pct = max_slippage_pct
        self._max_position_usd = max_position_usd
        self._order_guard = order_guard

        log.info(
            "execution_guard_initialized",
            min_liquidity_usd=min_liquidity_usd,
            max_slippage_pct=max_slippage_pct,
            max_position_usd=max_position_usd,
            order_guard_attached=order_guard is not None,
        )

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_config(
        cls,
        config: dict,
        order_guard: Optional[object] = None,
    ) -> "ExecutionGuard":
        """Build from configuration dict.

        Args:
            config: Top-level config dict.  Reads ``execution_guard`` sub-key.
            order_guard: Optional OrderGuard instance.

        Returns:
            Configured ExecutionGuard.
        """
        cfg = config.get("execution_guard", {})
        markets_cfg = config.get("markets", {})

        min_liquidity = float(
            cfg.get(
                "min_liquidity_usd",
                markets_cfg.get("min_liquidity_usd", _MIN_LIQUIDITY_USD),
            )
        )

        return cls(
            min_liquidity_usd=min_liquidity,
            max_slippage_pct=float(cfg.get("max_slippage_pct", _MAX_SLIPPAGE_PCT)),
            max_position_usd=float(cfg.get("max_position_usd", _MAX_POSITION_USD)),
            order_guard=order_guard,
        )

    # ── Validation ────────────────────────────────────────────────────────────

    def validate(
        self,
        market_id: str,
        side: str,
        price: float,
        size_usd: float,
        liquidity_usd: float,
        slippage_pct: float,
        order_guard_signature: Optional[str] = None,
    ) -> ValidationResult:
        """Run all pre-trade validation checks.

        Args:
            market_id: Polymarket condition ID.
            side: "YES" | "NO".
            price: Limit price (0–1).
            size_usd: Proposed order size in USD.
            liquidity_usd: Current orderbook depth estimate in USD.
            slippage_pct: Estimated execution slippage as a fraction (e.g. 0.01
                          = 1%).
            order_guard_signature: Pre-computed dedup signature.  If provided
                                   and the OrderGuard already holds this
                                   signature as active, the trade is rejected.

        Returns:
            ValidationResult with ``passed=True`` if every check passes.
        """
        checks: dict = {}
        rejection_reason = ""

        # ── 1. Liquidity ──────────────────────────────────────────────────────
        liquidity_ok = liquidity_usd >= self._min_liquidity_usd
        checks["liquidity"] = {
            "passed": liquidity_ok,
            "value": liquidity_usd,
            "threshold": self._min_liquidity_usd,
        }
        if not liquidity_ok and not rejection_reason:
            rejection_reason = (
                f"insufficient_liquidity:{liquidity_usd:.0f}"
                f"<{self._min_liquidity_usd:.0f}"
            )

        # ── 2. Slippage ───────────────────────────────────────────────────────
        slippage_ok = slippage_pct <= self._max_slippage_pct
        checks["slippage"] = {
            "passed": slippage_ok,
            "value": round(slippage_pct, 6),
            "threshold": self._max_slippage_pct,
        }
        if not slippage_ok and not rejection_reason:
            rejection_reason = (
                f"slippage_exceeded:{slippage_pct:.4f}>{self._max_slippage_pct:.4f}"
            )

        # ── 3. Position size ──────────────────────────────────────────────────
        size_ok = size_usd <= self._max_position_usd
        checks["position_size"] = {
            "passed": size_ok,
            "value": size_usd,
            "threshold": self._max_position_usd,
        }
        if not size_ok and not rejection_reason:
            rejection_reason = (
                f"position_size_exceeded:{size_usd:.2f}>{self._max_position_usd:.2f}"
            )

        # ── 4. Duplicate detection ────────────────────────────────────────────
        duplicate_blocked = False
        if order_guard_signature is not None and self._order_guard is not None:
            # Access the internal _active dict directly (read-only).
            # OrderGuard.try_claim() is async; we avoid calling it here to keep
            # validate() synchronous.  The caller should call try_claim()
            # independently as part of the execution pipeline.
            active: dict = getattr(self._order_guard, "_active", {})
            duplicate_blocked = order_guard_signature in active

        checks["no_duplicate"] = {
            "passed": not duplicate_blocked,
            "signature": order_guard_signature,
        }
        if duplicate_blocked and not rejection_reason:
            rejection_reason = (
                f"duplicate_order:{order_guard_signature}"
            )

        all_passed = all(c["passed"] for c in checks.values())

        if all_passed:
            log.debug(
                "execution_guard_validation_passed",
                market_id=market_id,
                side=side,
                price=price,
                size_usd=size_usd,
            )
        else:
            log.warning(
                "execution_guard_validation_failed",
                market_id=market_id,
                side=side,
                price=price,
                size_usd=size_usd,
                reason=rejection_reason,
                checks=checks,
            )

        return ValidationResult(
            passed=all_passed,
            reason=rejection_reason,
            checks=checks,
        )
