"""Phase 6 execution configuration.

All execution engine parameters in a single frozen dataclass.
Loaded from config.yaml via from_dict().
"""
from __future__ import annotations

from dataclasses import dataclass, fields


@dataclass(frozen=True)
class ExecutionConfig:
    """Immutable execution engine configuration for Phase 6.

    All cost, sizing, routing and fill-protection parameters.
    """

    # ── Fees ─────────────────────────────────────────────────────────────────
    taker_fee_pct: float = 0.02         # 2% taker fee fraction
    maker_fee_pct: float = 0.01         # 1% maker fee fraction

    # ── Slippage ──────────────────────────────────────────────────────────────
    slippage_bps: int = 50              # base slippage in basis points
    max_slippage_pct: float = 0.03      # abort order if slippage > 3%

    # ── Alpha buffer (volatility-adjusted cost cushion) ───────────────────────
    base_alpha_buffer: float = 0.005    # minimum cost buffer (0.5%)
    max_alpha_buffer: float = 0.05      # hard ceiling on alpha buffer (5%)
    volatility_scale: float = 2.0       # spread-implied vol multiplier

    # ── Maker / taker routing ─────────────────────────────────────────────────
    maker_spread_threshold: float = 0.02    # spread >= this → prefer MAKER
    maker_timeout_ms: int = 3000            # maker limit order timeout (ms)
    hybrid_ev_multiplier: float = 2.0       # EV > cost × this → force TAKER

    # ── Order sizing ──────────────────────────────────────────────────────────
    min_order_size: float = 5.0         # minimum viable order (USD)
    lot_step: float = 1.0               # minimum lot increment (USD)
    liquidity_cap_pct: float = 0.10     # max fraction of volume per order

    # ── Fill probability ──────────────────────────────────────────────────────
    fill_prob_threshold: float = 0.60   # min fill_prob to prefer MAKER

    # ── Position limits ───────────────────────────────────────────────────────
    max_position_pct: float = 0.10      # max 10% of balance per position
    max_open_positions: int = 5         # reject if at or above this count

    # ── Partial fill protection ───────────────────────────────────────────────
    max_partial_retries: int = 1        # strictly 1 taker retry
    partial_slippage_bps: int = 75      # tighter slippage limit on retry

    # ── Market depth simulation ───────────────────────────────────────────────
    market_depth_threshold: float = 50.0   # depth threshold for partial fills

    @classmethod
    def from_dict(cls, d: dict) -> "ExecutionConfig":
        """Build from a flat config dict (e.g., loaded from YAML execution block).

        Unknown keys are silently ignored so the YAML can contain extras.
        """
        known = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in d.items() if k in known}
        return cls(**filtered)
