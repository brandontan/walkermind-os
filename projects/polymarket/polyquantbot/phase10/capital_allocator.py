"""Phase 10.5 — CapitalAllocator: Strict position sizing with bankroll controls.

Computes the maximum permitted position size for a single trade, enforcing
hard capital rules derived from the Walker AI risk framework.

Capital rules (all enforced, no silent clamping)::

    initial_cap_pct       — 5% of bankroll is the initial deployment cap.
    max_per_trade_pct     — 2% of bankroll is the maximum single trade size.
    max_concurrent_trades — at most 2 concurrent open positions.
    max_total_exposure    — total exposure must remain ≤ 5% of bankroll.

Rejection policy::

    Oversize requests are REJECTED with a descriptive error — never silently
    clamped.  The caller must react to the rejection.

Determinism::

    No randomness.  Given the same inputs, the allocator always returns the
    same output.

Usage::

    allocator = CapitalAllocator(bankroll=10_000.0)
    size = allocator.compute_position_size(
        signal_strength=0.80,
        current_exposure=150.0,
        concurrent_trades=1,
    )
    # Returns position size in USD, or raises CapitalAllocationError.

Thread-safety: single asyncio event loop only.
"""
from __future__ import annotations

from dataclasses import dataclass

import structlog

log = structlog.get_logger()

# ── Defaults ──────────────────────────────────────────────────────────────────

_INITIAL_CAP_PCT: float = 0.05       # 5% bankroll cap
_MAX_PER_TRADE_PCT: float = 0.02     # 2% max per-trade
_MAX_CONCURRENT: int = 2             # max open positions
_MAX_TOTAL_EXPOSURE_PCT: float = 0.05  # 5% total exposure ceiling


# ── Error types ───────────────────────────────────────────────────────────────


class CapitalAllocationError(Exception):
    """Raised when a position request violates capital rules."""


# ── Result type ───────────────────────────────────────────────────────────────


@dataclass
class AllocationResult:
    """Result of a successful capital allocation computation.

    Attributes:
        position_size_usd: Approved position size in USD.
        bankroll: Bankroll used for the computation.
        signal_strength: Input signal strength (0.0–1.0).
        current_exposure: Current total open exposure in USD.
        concurrent_trades: Current number of open trades.
        max_per_trade_usd: Per-trade cap applied.
        remaining_exposure_usd: Available exposure headroom after this trade.
    """

    position_size_usd: float
    bankroll: float
    signal_strength: float
    current_exposure: float
    concurrent_trades: int
    max_per_trade_usd: float
    remaining_exposure_usd: float


# ── CapitalAllocator ──────────────────────────────────────────────────────────


class CapitalAllocator:
    """Deterministic position-size calculator with strict bankroll enforcement.

    Args:
        bankroll: Total available capital in USD.
        initial_cap_pct: Maximum fraction of bankroll for initial deployment.
        max_per_trade_pct: Maximum fraction of bankroll per single trade.
        max_concurrent_trades: Maximum number of simultaneously open trades.
        max_total_exposure_pct: Maximum fraction of bankroll in total exposure.
    """

    def __init__(
        self,
        bankroll: float,
        initial_cap_pct: float = _INITIAL_CAP_PCT,
        max_per_trade_pct: float = _MAX_PER_TRADE_PCT,
        max_concurrent_trades: int = _MAX_CONCURRENT,
        max_total_exposure_pct: float = _MAX_TOTAL_EXPOSURE_PCT,
    ) -> None:
        if bankroll <= 0:
            raise ValueError(f"bankroll must be positive, got {bankroll}")
        if not (0 < initial_cap_pct <= 1.0):
            raise ValueError(f"initial_cap_pct must be in (0, 1], got {initial_cap_pct}")
        if not (0 < max_per_trade_pct <= 1.0):
            raise ValueError(f"max_per_trade_pct must be in (0, 1], got {max_per_trade_pct}")
        if max_concurrent_trades < 1:
            raise ValueError(
                f"max_concurrent_trades must be >= 1, got {max_concurrent_trades}"
            )

        self._bankroll = bankroll
        self._initial_cap_pct = initial_cap_pct
        self._max_per_trade_pct = max_per_trade_pct
        self._max_concurrent = max_concurrent_trades
        self._max_total_exposure_pct = max_total_exposure_pct

        log.info(
            "capital_allocator_initialized",
            bankroll=bankroll,
            initial_cap_pct=initial_cap_pct,
            max_per_trade_pct=max_per_trade_pct,
            max_concurrent_trades=max_concurrent_trades,
            max_total_exposure_pct=max_total_exposure_pct,
        )

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_config(cls, config: dict) -> "CapitalAllocator":
        """Build from a configuration dict.

        Args:
            config: Top-level config dict.  Reads ``capital`` sub-key.

        Returns:
            Configured CapitalAllocator.
        """
        cfg = config.get("capital", {})
        bankroll = float(cfg.get("bankroll", 10_000.0))
        return cls(
            bankroll=bankroll,
            initial_cap_pct=float(cfg.get("initial_cap_pct", _INITIAL_CAP_PCT)),
            max_per_trade_pct=float(cfg.get("max_per_trade_pct", _MAX_PER_TRADE_PCT)),
            max_concurrent_trades=int(cfg.get("max_concurrent_trades", _MAX_CONCURRENT)),
            max_total_exposure_pct=float(
                cfg.get("max_total_exposure_pct", _MAX_TOTAL_EXPOSURE_PCT)
            ),
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def compute_position_size(
        self,
        signal_strength: float,
        current_exposure: float,
        concurrent_trades: int,
    ) -> AllocationResult:
        """Compute the maximum permitted position size for a single trade.

        All rules are checked in order; the first violation raises
        :class:`CapitalAllocationError`.

        Args:
            signal_strength: Signal confidence score ∈ [0.0, 1.0].
                Used to scale size within the per-trade cap.
            current_exposure: Total USD currently allocated to open positions.
            concurrent_trades: Number of positions currently open.

        Returns:
            :class:`AllocationResult` with the validated position size.

        Raises:
            CapitalAllocationError: If any capital rule is violated.
        """
        if not (0.0 <= signal_strength <= 1.0):
            raise CapitalAllocationError(
                f"signal_strength must be in [0.0, 1.0], got {signal_strength}"
            )
        if current_exposure < 0:
            raise CapitalAllocationError(
                f"current_exposure must be >= 0, got {current_exposure}"
            )
        if concurrent_trades < 0:
            raise CapitalAllocationError(
                f"concurrent_trades must be >= 0, got {concurrent_trades}"
            )

        max_per_trade_usd = self._bankroll * self._max_per_trade_pct
        max_total_exposure_usd = self._bankroll * self._max_total_exposure_pct

        # ── Rule 1: concurrent trade cap ─────────────────────────────────────
        if concurrent_trades >= self._max_concurrent:
            raise CapitalAllocationError(
                f"concurrent_trades_cap_reached: "
                f"{concurrent_trades} >= {self._max_concurrent}"
            )

        # ── Rule 2: total exposure cap ────────────────────────────────────────
        remaining_exposure = max_total_exposure_usd - current_exposure
        if remaining_exposure <= 0:
            raise CapitalAllocationError(
                f"total_exposure_cap_reached: "
                f"current={current_exposure:.2f} >= max={max_total_exposure_usd:.2f}"
            )

        # ── Rule 3: compute signal-scaled size ────────────────────────────────
        # Size scales linearly with signal strength up to per-trade cap.
        # A signal_strength of 1.0 yields max_per_trade_usd.
        raw_size = max_per_trade_usd * signal_strength

        # ── Rule 4: enforce per-trade cap (reject oversize, do not clamp) ─────
        if raw_size > max_per_trade_usd:
            raise CapitalAllocationError(
                f"per_trade_cap_exceeded: "
                f"{raw_size:.2f} > {max_per_trade_usd:.2f}"
            )

        # ── Rule 5: enforce total exposure cap ────────────────────────────────
        if raw_size > remaining_exposure:
            raise CapitalAllocationError(
                f"total_exposure_cap_exceeded: "
                f"requested={raw_size:.2f}, remaining={remaining_exposure:.2f}"
            )

        # ── Rule 6: enforce initial deployment cap ────────────────────────────
        initial_cap_usd = self._bankroll * self._initial_cap_pct
        projected_exposure = current_exposure + raw_size
        if projected_exposure > initial_cap_usd:
            raise CapitalAllocationError(
                f"initial_cap_exceeded: "
                f"projected={projected_exposure:.2f} > initial_cap={initial_cap_usd:.2f}"
            )

        result = AllocationResult(
            position_size_usd=raw_size,
            bankroll=self._bankroll,
            signal_strength=signal_strength,
            current_exposure=current_exposure,
            concurrent_trades=concurrent_trades,
            max_per_trade_usd=max_per_trade_usd,
            remaining_exposure_usd=remaining_exposure - raw_size,
        )

        log.info(
            "capital_allocator_allocation",
            position_size_usd=round(raw_size, 2),
            bankroll=self._bankroll,
            signal_strength=signal_strength,
            current_exposure=round(current_exposure, 2),
            concurrent_trades=concurrent_trades,
            remaining_exposure_usd=round(result.remaining_exposure_usd, 2),
        )

        return result

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def bankroll(self) -> float:
        """Current bankroll in USD."""
        return self._bankroll

    @property
    def max_per_trade_usd(self) -> float:
        """Per-trade size cap in USD."""
        return self._bankroll * self._max_per_trade_pct

    @property
    def max_total_exposure_usd(self) -> float:
        """Total exposure cap in USD."""
        return self._bankroll * self._max_total_exposure_pct
