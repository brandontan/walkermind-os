"""Phase 10.6 — ConfigManager: Runtime-mutable trading configuration.

Provides a thread-safe (asyncio.Lock protected) configuration store that
can be updated at runtime via Telegram commands or operator tools without
restarting the trading system.

Fields:
    risk_multiplier   — Kelly fraction multiplier (0.0–1.0, default 0.25)
    max_position      — Maximum position as fraction of bankroll (0.0–0.10)

Validation rules:
    risk_multiplier must be in [0.0, 1.0]   — clamped to range
    max_position must be in [0.0, 0.10]     — clamped to range (max 10%)

Usage::

    cfg = ConfigManager()
    await cfg.set_risk_multiplier(0.5)
    await cfg.set_max_position(0.08)
    snapshot = cfg.snapshot()

Thread-safety: single asyncio event loop only.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Optional

import structlog

log = structlog.get_logger()

# ── Defaults (production-safe) ─────────────────────────────────────────────────

_DEFAULT_RISK_MULTIPLIER: float = 0.25    # α = 0.25 (never full Kelly)
_DEFAULT_MAX_POSITION: float = 0.10       # 10% bankroll max

# ── Hard limits (cannot be exceeded) ──────────────────────────────────────────

_RISK_MULTIPLIER_MIN: float = 0.0
_RISK_MULTIPLIER_MAX: float = 1.0
_MAX_POSITION_MIN: float = 0.0
_MAX_POSITION_MAX: float = 0.10           # 10% hard cap


@dataclass
class RuntimeConfig:
    """Snapshot of the current runtime configuration.

    Attributes:
        risk_multiplier: Kelly fraction multiplier (0.0–1.0).
        max_position: Maximum position as fraction of bankroll (0.0–0.10).
        updated_at: Unix epoch of the last update.
    """

    risk_multiplier: float
    max_position: float
    updated_at: float


class ConfigManager:
    """Asyncio-safe runtime configuration store.

    All mutating methods acquire an asyncio.Lock to prevent concurrent
    writes from racing.  Read access (snapshot / properties) is lock-free
    and returns a consistent copy.

    Args:
        risk_multiplier: Initial risk multiplier (default 0.25).
        max_position: Initial max position fraction (default 0.10).
    """

    def __init__(
        self,
        risk_multiplier: float = _DEFAULT_RISK_MULTIPLIER,
        max_position: float = _DEFAULT_MAX_POSITION,
    ) -> None:
        self._risk_multiplier = self._clamp_risk(risk_multiplier)
        self._max_position = self._clamp_position(max_position)
        self._lock = asyncio.Lock()
        self._updated_at = time.time()

        log.info(
            "config_manager_initialized",
            risk_multiplier=self._risk_multiplier,
            max_position=self._max_position,
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

    def snapshot(self) -> RuntimeConfig:
        """Return an immutable snapshot of the current configuration.

        Returns:
            RuntimeConfig with current values.
        """
        return RuntimeConfig(
            risk_multiplier=self._risk_multiplier,
            max_position=self._max_position,
            updated_at=self._updated_at,
        )

    # ── Mutating methods ───────────────────────────────────────────────────────

    async def set_risk_multiplier(self, value: float) -> float:
        """Set the risk multiplier with validation and clamping.

        Values outside [0.0, 1.0] are clamped to the nearest valid boundary.

        Args:
            value: Desired risk multiplier.

        Returns:
            The applied value after clamping.

        Raises:
            ValueError: If value is not a finite number.
        """
        self._validate_finite(value, "risk_multiplier")
        clamped = self._clamp_risk(value)
        async with self._lock:
            prev = self._risk_multiplier
            self._risk_multiplier = clamped
            self._updated_at = time.time()
        log.info(
            "config_manager_risk_multiplier_updated",
            previous=prev,
            applied=clamped,
            requested=value,
            clamped=(abs(value - clamped) > 1e-9),
        )
        return clamped

    async def set_max_position(self, value: float) -> float:
        """Set the max position fraction with validation and clamping.

        Values outside [0.0, 0.10] are clamped to the nearest valid boundary.

        Args:
            value: Desired max position fraction.

        Returns:
            The applied value after clamping.

        Raises:
            ValueError: If value is not a finite number.
        """
        self._validate_finite(value, "max_position")
        clamped = self._clamp_position(value)
        async with self._lock:
            prev = self._max_position
            self._max_position = clamped
            self._updated_at = time.time()
        log.info(
            "config_manager_max_position_updated",
            previous=prev,
            applied=clamped,
            requested=value,
            clamped=(abs(value - clamped) > 1e-9),
        )
        return clamped

    # ── Validation helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _clamp_risk(value: float) -> float:
        return max(_RISK_MULTIPLIER_MIN, min(_RISK_MULTIPLIER_MAX, value))

    @staticmethod
    def _clamp_position(value: float) -> float:
        return max(_MAX_POSITION_MIN, min(_MAX_POSITION_MAX, value))

    @staticmethod
    def _validate_finite(value: float, field: str) -> None:
        import math
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(
                f"ConfigManager.{field}: expected finite float, got {value!r}"
            )
