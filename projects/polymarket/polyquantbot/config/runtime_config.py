"""Phase 10.6 — ConfigManager: Runtime-mutable trading configuration.

Provides a thread-safe (asyncio.Lock protected) configuration store that
can be updated at runtime via Telegram commands or operator tools without
restarting the trading system.

Fields:
    risk_multiplier   — Kelly fraction multiplier (0.0–1.0, default 0.25)
    max_position      — Maximum position as fraction of bankroll (0.0–0.10)
    max_markets       — Maximum markets to auto-discover (1–50, default 5)
    min_liquidity_usd — Minimum USD liquidity for auto-discovery (1k–1M, default 10k)
    market_ids        — Currently active market condition IDs (list of str)

Validation rules:
    risk_multiplier must be in [0.0, 1.0]   — clamped to range
    max_position must be in [0.0, 0.10]     — clamped to range (max 10%)
    max_markets must be in [1, 50]          — clamped to range
    min_liquidity_usd must be in [1000, 1_000_000] — clamped to range

Usage::

    cfg = ConfigManager()
    await cfg.set_risk_multiplier(0.5)
    await cfg.set_max_position(0.08)
    await cfg.set_max_markets(10)
    await cfg.set_min_liquidity_usd(25000)
    cfg.update_market_ids(["0xabc...", "0xdef..."])
    snapshot = cfg.snapshot()

Thread-safety: single asyncio event loop only.
"""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from typing import List, Optional

import structlog

log = structlog.get_logger()

# ── Defaults (production-safe) ─────────────────────────────────────────────────

_DEFAULT_RISK_MULTIPLIER: float = 0.25    # α = 0.25 (never full Kelly)
_DEFAULT_MAX_POSITION: float = 0.10       # 10% bankroll max
_DEFAULT_MAX_MARKETS: int = 5
_DEFAULT_MIN_LIQUIDITY_USD: float = 10_000.0

# ── Hard limits (cannot be exceeded) ──────────────────────────────────────────

_RISK_MULTIPLIER_MIN: float = 0.0
_RISK_MULTIPLIER_MAX: float = 1.0
_MAX_POSITION_MIN: float = 0.0
_MAX_POSITION_MAX: float = 0.10           # 10% hard cap
_MAX_MARKETS_MIN: int = 1
_MAX_MARKETS_MAX: int = 50
_MIN_LIQUIDITY_MIN: float = 1_000.0
_MIN_LIQUIDITY_MAX: float = 1_000_000.0


@dataclass
class RuntimeConfig:
    """Snapshot of the current runtime configuration.

    Attributes:
        risk_multiplier: Kelly fraction multiplier (0.0–1.0).
        max_position: Maximum position as fraction of bankroll (0.0–0.10).
        max_markets: Max markets to auto-discover (1–50).
        min_liquidity_usd: Min USD liquidity threshold for discovery.
        market_ids: Currently active market condition IDs.
        updated_at: Unix epoch of the last update.
    """

    risk_multiplier: float
    max_position: float
    max_markets: int
    min_liquidity_usd: float
    market_ids: List[str]
    updated_at: float


class ConfigManager:
    """Asyncio-safe runtime configuration store.

    All mutating methods acquire an asyncio.Lock to prevent concurrent
    writes from racing.  Read access (snapshot / properties) is lock-free
    and returns a consistent copy.

    Args:
        risk_multiplier: Initial risk multiplier (default 0.25).
        max_position: Initial max position fraction (default 0.10).
        max_markets: Initial max markets for auto-discovery (default from env or 5).
        min_liquidity_usd: Initial min liquidity for discovery (default from env or 10k).
    """

    def __init__(
        self,
        risk_multiplier: float = _DEFAULT_RISK_MULTIPLIER,
        max_position: float = _DEFAULT_MAX_POSITION,
        max_markets: Optional[int] = None,
        min_liquidity_usd: Optional[float] = None,
    ) -> None:
        self._risk_multiplier = self._clamp_risk(risk_multiplier)
        self._max_position = self._clamp_position(max_position)
        # Read market discovery settings from env if not provided explicitly
        self._max_markets = self._clamp_max_markets(
            max_markets if max_markets is not None
            else int(os.environ.get("MAX_MARKETS", str(_DEFAULT_MAX_MARKETS)))
        )
        self._min_liquidity_usd = self._clamp_liquidity(
            min_liquidity_usd if min_liquidity_usd is not None
            else float(os.environ.get("MIN_LIQUIDITY_USD", str(_DEFAULT_MIN_LIQUIDITY_USD)))
        )
        self._market_ids: List[str] = []
        self._lock = asyncio.Lock()
        self._updated_at = time.time()

        log.info(
            "config_manager_initialized",
            risk_multiplier=self._risk_multiplier,
            max_position=self._max_position,
            max_markets=self._max_markets,
            min_liquidity_usd=self._min_liquidity_usd,
        )

    # ── Read-only accessors ────────────────────────────────────────────────────

    @property
    def risk_multiplier(self) -> float:
        """Current risk multiplier (lock-free snapshot)."""
        return self._risk_multiplier

    @property
    def max_position(self) -> float:
        """Current max position fraction (lock-free snapshot)."""
        return self._max_position

    @property
    def max_markets(self) -> int:
        """Current max markets for auto-discovery."""
        return self._max_markets

    @property
    def min_liquidity_usd(self) -> float:
        """Current minimum liquidity threshold for auto-discovery."""
        return self._min_liquidity_usd

    @property
    def market_ids(self) -> List[str]:
        """Currently active market IDs (copy)."""
        return list(self._market_ids)

    def snapshot(self) -> RuntimeConfig:
        """Return an immutable snapshot of the current configuration."""
        return RuntimeConfig(
            risk_multiplier=self._risk_multiplier,
            max_position=self._max_position,
            max_markets=self._max_markets,
            min_liquidity_usd=self._min_liquidity_usd,
            market_ids=list(self._market_ids),
            updated_at=self._updated_at,
        )

    # ── Mutating methods ───────────────────────────────────────────────────────

    async def set_risk_multiplier(self, value: float) -> float:
        """Set the risk multiplier with validation and clamping."""
        self._validate_finite(value, "risk_multiplier")
        clamped = self._clamp_risk(value)
        async with self._lock:
            prev = self._risk_multiplier
            self._risk_multiplier = clamped
            self._updated_at = time.time()
        log.info(
            "config_manager_risk_multiplier_updated",
            previous=prev, applied=clamped, requested=value,
        )
        return clamped

    async def set_max_position(self, value: float) -> float:
        """Set the max position fraction with validation and clamping."""
        self._validate_finite(value, "max_position")
        clamped = self._clamp_position(value)
        async with self._lock:
            prev = self._max_position
            self._max_position = clamped
            self._updated_at = time.time()
        log.info(
            "config_manager_max_position_updated",
            previous=prev, applied=clamped, requested=value,
        )
        return clamped

    async def set_max_markets(self, value: int) -> int:
        """Set the maximum number of auto-discovered markets (1–50).

        Args:
            value: Desired market count.

        Returns:
            The applied value after clamping.
        """
        if not isinstance(value, (int, float)):
            raise ValueError(f"max_markets: expected int, got {value!r}")
        clamped = self._clamp_max_markets(int(value))
        async with self._lock:
            prev = self._max_markets
            self._max_markets = clamped
            self._updated_at = time.time()
        log.info(
            "config_manager_max_markets_updated",
            previous=prev, applied=clamped, requested=value,
        )
        return clamped

    async def set_min_liquidity_usd(self, value: float) -> float:
        """Set the minimum liquidity threshold for auto-discovery.

        Args:
            value: Desired minimum USD liquidity (1k–1M).

        Returns:
            The applied value after clamping.
        """
        self._validate_finite(value, "min_liquidity_usd")
        clamped = self._clamp_liquidity(value)
        async with self._lock:
            prev = self._min_liquidity_usd
            self._min_liquidity_usd = clamped
            self._updated_at = time.time()
        log.info(
            "config_manager_min_liquidity_updated",
            previous=prev, applied=clamped, requested=value,
        )
        return clamped

    def update_market_ids(self, market_ids: List[str]) -> None:
        """Update the active market IDs list (sync, no lock needed for list replace).

        Args:
            market_ids: New list of Polymarket condition IDs.
        """
        prev_count = len(self._market_ids)
        self._market_ids = list(market_ids)
        self._updated_at = time.time()
        log.info(
            "config_manager_market_ids_updated",
            previous_count=prev_count,
            new_count=len(self._market_ids),
            market_ids=self._market_ids[:5],
        )

    # ── Validation helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _clamp_risk(value: float) -> float:
        return max(_RISK_MULTIPLIER_MIN, min(_RISK_MULTIPLIER_MAX, value))

    @staticmethod
    def _clamp_position(value: float) -> float:
        return max(_MAX_POSITION_MIN, min(_MAX_POSITION_MAX, value))

    @staticmethod
    def _clamp_max_markets(value: int) -> int:
        return max(_MAX_MARKETS_MIN, min(_MAX_MARKETS_MAX, value))

    @staticmethod
    def _clamp_liquidity(value: float) -> float:
        return max(_MIN_LIQUIDITY_MIN, min(_MIN_LIQUIDITY_MAX, value))

    @staticmethod
    def _validate_finite(value: float, field: str) -> None:
        import math
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(
                f"ConfigManager.{field}: expected finite float, got {value!r}"
            )
