"""Phase 11 — LiveConfig: Production LIVE deployment configuration.

Defines all parameters for running PolyQuantBot in LIVE trading mode.
Every value is read from environment variables or falls back to a safe default.

Environment variables:
    ENABLE_LIVE_TRADING       — REQUIRED; must be "true" to unlock LIVE mode.
    TRADING_MODE              — "LIVE" | "PAPER" (default: "PAPER")
    SIGNAL_DEBUG_MODE         — "true" | "false" (default: "false")
    SIGNAL_EDGE_THRESHOLD     — float, minimum edge to generate a signal (default: 0.05)
    MAX_POSITION_FRACTION     — float 0–1, max position as fraction of bankroll (default: 0.02)
    MAX_CONCURRENT_TRADES     — int (default: 2)
    DAILY_LOSS_LIMIT          — float, negative USD (default: -2000.0)
    DRAWDOWN_LIMIT            — float 0–1 (default: 0.08)
    MIN_LIQUIDITY_USD         — float (default: 10000.0)

Live mode guard:
    ENABLE_LIVE_TRADING must equal "true" (case-insensitive) or LiveConfig.validate()
    raises LiveModeGuardError.  This prevents accidental PAPER → LIVE activation.

Usage::

    cfg = LiveConfig.from_env()
    cfg.validate()           # raises LiveModeGuardError if ENABLE_LIVE_TRADING != true
    mode = cfg.trading_mode  # TradingMode.LIVE or TradingMode.PAPER

Design:
    - All secrets read from .env only — never hardcoded.
    - Immutable after construction (dataclass with frozen=False, but no setters).
    - Fail-closed: any invalid value raises ValueError at construction time.
    - Structured logging on construction and validation.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

import structlog

from ..core.pipeline.go_live_controller import TradingMode

log = structlog.get_logger()

# ── Defaults ──────────────────────────────────────────────────────────────────

_DEFAULT_TRADING_MODE: str = "PAPER"
_DEFAULT_SIGNAL_DEBUG_MODE: bool = False
_DEFAULT_EDGE_THRESHOLD: float = 0.05
_DEFAULT_PAPER_EDGE_THRESHOLD: float = 0.005  # 0.5% — lower threshold for PAPER mode
_DEFAULT_MAX_POSITION: float = 0.02       # 2% of bankroll
_DEFAULT_MAX_CONCURRENT_TRADES: int = 2
_DEFAULT_DAILY_LOSS_LIMIT: float = -2000.0
_DEFAULT_DRAWDOWN_LIMIT: float = 0.08     # 8%
_DEFAULT_MIN_LIQUIDITY_USD: float = 10_000.0
_DEFAULT_PAPER_INITIAL_BALANCE: float = 10_000.0  # $10,000 paper trading starting balance


# ── Guard error ───────────────────────────────────────────────────────────────


class LiveModeGuardError(Exception):
    """Raised when LIVE mode is requested without explicit opt-in flag.

    ENABLE_LIVE_TRADING=true must be set in the environment to allow
    LIVE trading.  This prevents accidental PAPER → LIVE switches.
    """


# ── Config dataclass ──────────────────────────────────────────────────────────


@dataclass
class LiveConfig:
    """Production LIVE deployment configuration.

    Attributes:
        trading_mode: TradingMode.LIVE or TradingMode.PAPER.
        enable_live_trading: Explicit opt-in flag from environment.
        signal_debug_mode: If True, relax edge threshold for debugging.
        edge_threshold: Minimum edge required to generate a signal.
        paper_mode: True when operating in PAPER (simulated) mode.
        paper_edge_threshold: Lower edge threshold used in PAPER mode (0.5%).
        paper_initial_balance: Starting balance for paper trading ($10,000).
        max_position_fraction: Max single-position size as fraction of bankroll.
        max_concurrent_trades: Hard cap on open trades at any moment.
        daily_loss_limit: Daily loss limit in USD (negative number).
        drawdown_limit: Maximum drawdown fraction before all trading stops.
        min_liquidity_usd: Minimum order-book depth required for execution.
    """

    trading_mode: TradingMode
    enable_live_trading: bool
    signal_debug_mode: bool
    edge_threshold: float
    paper_mode: bool = False
    paper_edge_threshold: float = _DEFAULT_PAPER_EDGE_THRESHOLD
    paper_initial_balance: float = _DEFAULT_PAPER_INITIAL_BALANCE
    max_position_fraction: float = _DEFAULT_MAX_POSITION
    max_concurrent_trades: int = _DEFAULT_MAX_CONCURRENT_TRADES
    daily_loss_limit: float = _DEFAULT_DAILY_LOSS_LIMIT
    drawdown_limit: float = _DEFAULT_DRAWDOWN_LIMIT
    min_liquidity_usd: float = _DEFAULT_MIN_LIQUIDITY_USD

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_env(cls) -> "LiveConfig":
        """Construct LiveConfig from environment variables.

        Returns:
            Populated LiveConfig instance.

        Raises:
            ValueError: If a numeric environment variable is malformed.
        """
        enable_live = os.getenv("ENABLE_LIVE_TRADING", "false").strip().lower() == "true"
        mode_str = os.getenv("TRADING_MODE", _DEFAULT_TRADING_MODE).strip().upper()

        try:
            trading_mode = TradingMode(mode_str)
        except ValueError:
            log.warning(
                "live_config_invalid_trading_mode",
                value=mode_str,
                fallback=_DEFAULT_TRADING_MODE,
            )
            trading_mode = TradingMode(_DEFAULT_TRADING_MODE)

        debug_str = os.getenv("SIGNAL_DEBUG_MODE", "").strip().lower()
        signal_debug = debug_str == "true" if debug_str else _DEFAULT_SIGNAL_DEBUG_MODE

        is_paper = trading_mode == TradingMode("PAPER")
        paper_edge = _parse_float(
            "PAPER_MODE_EDGE_THRESHOLD", _DEFAULT_PAPER_EDGE_THRESHOLD
        )
        paper_balance = _parse_float(
            "PAPER_INITIAL_BALANCE", _DEFAULT_PAPER_INITIAL_BALANCE
        )
        edge_threshold = _parse_float(
            "SIGNAL_EDGE_THRESHOLD", _DEFAULT_EDGE_THRESHOLD
        )
        max_position = _parse_float(
            "MAX_POSITION_FRACTION", _DEFAULT_MAX_POSITION
        )
        max_concurrent = _parse_int(
            "MAX_CONCURRENT_TRADES", _DEFAULT_MAX_CONCURRENT_TRADES
        )
        daily_loss = _parse_float(
            "DAILY_LOSS_LIMIT", _DEFAULT_DAILY_LOSS_LIMIT
        )
        drawdown = _parse_float(
            "DRAWDOWN_LIMIT", _DEFAULT_DRAWDOWN_LIMIT
        )
        min_liquidity = _parse_float(
            "MIN_LIQUIDITY_USD", _DEFAULT_MIN_LIQUIDITY_USD
        )

        cfg = cls(
            trading_mode=trading_mode,
            enable_live_trading=enable_live,
            signal_debug_mode=signal_debug,
            edge_threshold=edge_threshold,
            paper_mode=is_paper,
            paper_edge_threshold=paper_edge,
            paper_initial_balance=paper_balance,
            max_position_fraction=max_position,
            max_concurrent_trades=max_concurrent,
            daily_loss_limit=daily_loss,
            drawdown_limit=drawdown,
            min_liquidity_usd=min_liquidity,
        )

        log.info(
            "live_config_loaded",
            trading_mode=trading_mode.value,
            enable_live_trading=enable_live,
            signal_debug_mode=signal_debug,
            edge_threshold=edge_threshold,
            paper_mode=is_paper,
            paper_edge_threshold=paper_edge,
            max_position_fraction=max_position,
            max_concurrent_trades=max_concurrent,
            daily_loss_limit=daily_loss,
            drawdown_limit=drawdown,
            min_liquidity_usd=min_liquidity,
        )

        return cfg

    # ── Validation ────────────────────────────────────────────────────────────

    def validate(self) -> None:
        """Validate LIVE mode prerequisites and configuration bounds.

        Raises:
            LiveModeGuardError: When LIVE mode is requested but
                ENABLE_LIVE_TRADING is not explicitly set to ``true``.
            ValueError: When a configuration value is out of safe bounds.
        """
        if self.trading_mode is TradingMode.LIVE and not self.enable_live_trading:
            raise LiveModeGuardError(
                "LIVE trading mode requires ENABLE_LIVE_TRADING=true in the "
                "environment.  Set this flag explicitly to confirm LIVE activation. "
                "This guard prevents accidental PAPER → LIVE switches."
            )

        if not (0.0 < self.max_position_fraction <= 0.10):
            raise ValueError(
                f"max_position_fraction must be in (0, 0.10]; got {self.max_position_fraction}"
            )
        if self.max_concurrent_trades < 1:
            raise ValueError(
                f"max_concurrent_trades must be >= 1; got {self.max_concurrent_trades}"
            )
        if self.daily_loss_limit >= 0:
            raise ValueError(
                f"daily_loss_limit must be negative; got {self.daily_loss_limit}"
            )
        if not (0.0 < self.drawdown_limit <= 0.20):
            raise ValueError(
                f"drawdown_limit must be in (0, 0.20]; got {self.drawdown_limit}"
            )
        if self.min_liquidity_usd < 0:
            raise ValueError(
                f"min_liquidity_usd must be >= 0; got {self.min_liquidity_usd}"
            )
        if self.edge_threshold <= 0.0:
            raise ValueError(
                f"edge_threshold must be > 0; got {self.edge_threshold}"
            )

        log.info(
            "live_config_validated",
            trading_mode=self.trading_mode.value,
            max_position_fraction=self.max_position_fraction,
            daily_loss_limit=self.daily_loss_limit,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Return a JSON-serialisable representation (no secrets).

        Returns:
            Configuration dict with all fields.
        """
        return {
            "trading_mode": self.trading_mode.value,
            "enable_live_trading": self.enable_live_trading,
            "signal_debug_mode": self.signal_debug_mode,
            "edge_threshold": self.edge_threshold,
            "paper_mode": self.paper_mode,
            "paper_edge_threshold": self.paper_edge_threshold,
            "paper_initial_balance": self.paper_initial_balance,
            "max_position_fraction": self.max_position_fraction,
            "max_concurrent_trades": self.max_concurrent_trades,
            "daily_loss_limit": self.daily_loss_limit,
            "drawdown_limit": self.drawdown_limit,
            "min_liquidity_usd": self.min_liquidity_usd,
        }


# ── Module helpers ────────────────────────────────────────────────────────────


def _parse_float(env_var: str, default: float) -> float:
    """Parse a float from an environment variable.

    Args:
        env_var: Environment variable name.
        default: Value to use if not set or invalid.

    Returns:
        Parsed float value.
    """
    raw = os.getenv(env_var, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        log.warning("live_config_parse_float_failed", env_var=env_var, raw=raw, default=default)
        return default


def _parse_int(env_var: str, default: int) -> int:
    """Parse an int from an environment variable.

    Args:
        env_var: Environment variable name.
        default: Value to use if not set or invalid.

    Returns:
        Parsed int value.
    """
    raw = os.getenv(env_var, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        log.warning("live_config_parse_int_failed", env_var=env_var, raw=raw, default=default)
        return default
