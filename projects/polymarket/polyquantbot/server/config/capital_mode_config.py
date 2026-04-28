"""Capital mode configuration and guard for CrusaderBot server layer.

This is the server-layer capital mode config — separate from the legacy
config/live_config.py which belongs to the old pipeline. This model governs
whether the new server domain (settlement, orchestration, portfolio, risk)
may operate with real capital.

All gates default to OFF. Every gate must be explicitly set in the environment
before capital mode can activate. This prevents any single misconfiguration from
enabling live trading.

Gates (all required for LIVE — any missing → CapitalModeGuardError):
    ENABLE_LIVE_TRADING=true           Base live trading opt-in (existing guard)
    CAPITAL_MODE_CONFIRMED=true        Explicit second confirmation (new gate)
    RISK_CONTROLS_VALIDATED=true       Set after P8-B SENTINEL MAJOR approval
    EXECUTION_PATH_VALIDATED=true      Set after P8-C SENTINEL MAJOR approval
    SECURITY_HARDENING_VALIDATED=true  Set after P8-D SENTINEL MAJOR approval

Risk constants (LOCKED — never change without SENTINEL MAJOR re-sweep):
    Kelly fraction:    0.25 (fractional Kelly only — full Kelly FORBIDDEN)
    Max position:      <= 10% of capital
    Daily loss limit:  negative USD value (hard stop)
    Drawdown limit:    <= 8%
    Min liquidity:     configurable, >= 0

Usage::

    cfg = CapitalModeConfig.from_env()
    cfg.validate()   # raises CapitalModeGuardError if LIVE but any gate off
    if cfg.is_capital_mode_allowed():
        # proceed with live execution
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import structlog

log = structlog.get_logger(__name__)

# ── Locked risk constants ─────────────────────────────────────────────────────

KELLY_FRACTION: float = 0.25
MAX_POSITION_FRACTION_CAP: float = 0.10
DRAWDOWN_LIMIT_CAP: float = 0.08

# ── Defaults ──────────────────────────────────────────────────────────────────

_DEFAULT_TRADING_MODE: str = "PAPER"
_DEFAULT_MAX_POSITION_FRACTION: float = 0.02
_DEFAULT_DAILY_LOSS_LIMIT_USD: float = -2000.0
_DEFAULT_DRAWDOWN_LIMIT_PCT: float = 0.08
_DEFAULT_MIN_LIQUIDITY_USD: float = 10_000.0


# ── Guard error ───────────────────────────────────────────────────────────────


class CapitalModeGuardError(Exception):
    """Raised when capital mode (LIVE) is requested but one or more gates are off.

    All five gates must be explicitly set to allow LIVE trading. This guard
    prevents any single env misconfiguration from enabling live execution.
    """


# ── Config dataclass ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CapitalModeConfig:
    """Multi-gate capital mode configuration for the CrusaderBot server layer.

    All boolean gate fields default to False. Operator must set each gate
    explicitly in the environment. validate() enforces this contract.

    Attributes:
        trading_mode: "PAPER" or "LIVE".
        enable_live_trading: Gate 1 — ENABLE_LIVE_TRADING=true.
        capital_mode_confirmed: Gate 2 — CAPITAL_MODE_CONFIRMED=true.
        risk_controls_validated: Gate 3 — RISK_CONTROLS_VALIDATED=true (P8-B).
        execution_path_validated: Gate 4 — EXECUTION_PATH_VALIDATED=true (P8-C).
        security_hardening_validated: Gate 5 — SECURITY_HARDENING_VALIDATED=true (P8-D).
        kelly_fraction: Always 0.25 — fractional Kelly, never 1.0.
        max_position_fraction: Max single position as fraction of capital (<= 0.10).
        daily_loss_limit_usd: Daily loss hard stop in USD (must be negative).
        drawdown_limit_pct: Max drawdown before auto-halt (<= 0.08).
        min_liquidity_usd: Minimum order-book depth required for execution (>= 0).
    """

    trading_mode: str
    enable_live_trading: bool
    capital_mode_confirmed: bool
    risk_controls_validated: bool
    execution_path_validated: bool
    security_hardening_validated: bool
    kelly_fraction: float
    max_position_fraction: float
    daily_loss_limit_usd: float
    drawdown_limit_pct: float
    min_liquidity_usd: float

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_env(cls) -> "CapitalModeConfig":
        """Construct CapitalModeConfig from environment variables.

        All gates default to False. Risk values have safe defaults.

        Raises:
            ValueError: If a numeric env var is malformed.
        """
        trading_mode = os.getenv("TRADING_MODE", _DEFAULT_TRADING_MODE).strip().upper()
        if trading_mode not in {"PAPER", "LIVE"}:
            log.warning(
                "capital_mode_config_invalid_trading_mode",
                value=trading_mode,
                fallback=_DEFAULT_TRADING_MODE,
            )
            trading_mode = _DEFAULT_TRADING_MODE

        enable_live = _flag("ENABLE_LIVE_TRADING")
        capital_confirmed = _flag("CAPITAL_MODE_CONFIRMED")
        risk_validated = _flag("RISK_CONTROLS_VALIDATED")
        execution_validated = _flag("EXECUTION_PATH_VALIDATED")
        security_validated = _flag("SECURITY_HARDENING_VALIDATED")

        max_position = _parse_float("CAPITAL_MAX_POSITION_FRACTION", _DEFAULT_MAX_POSITION_FRACTION)
        daily_loss = _parse_float("CAPITAL_DAILY_LOSS_LIMIT_USD", _DEFAULT_DAILY_LOSS_LIMIT_USD)
        drawdown = _parse_float("CAPITAL_DRAWDOWN_LIMIT_PCT", _DEFAULT_DRAWDOWN_LIMIT_PCT)
        min_liquidity = _parse_float("CAPITAL_MIN_LIQUIDITY_USD", _DEFAULT_MIN_LIQUIDITY_USD)

        cfg = cls(
            trading_mode=trading_mode,
            enable_live_trading=enable_live,
            capital_mode_confirmed=capital_confirmed,
            risk_controls_validated=risk_validated,
            execution_path_validated=execution_validated,
            security_hardening_validated=security_validated,
            kelly_fraction=KELLY_FRACTION,
            max_position_fraction=max_position,
            daily_loss_limit_usd=daily_loss,
            drawdown_limit_pct=drawdown,
            min_liquidity_usd=min_liquidity,
        )

        log.info(
            "capital_mode_config_loaded",
            trading_mode=trading_mode,
            enable_live_trading=enable_live,
            capital_mode_confirmed=capital_confirmed,
            risk_controls_validated=risk_validated,
            execution_path_validated=execution_validated,
            security_hardening_validated=security_validated,
            kelly_fraction=KELLY_FRACTION,
            max_position_fraction=max_position,
            daily_loss_limit_usd=daily_loss,
            drawdown_limit_pct=drawdown,
        )

        return cfg

    # ── Guard ─────────────────────────────────────────────────────────────────

    def is_capital_mode_allowed(self) -> bool:
        """Return True only when ALL five gates are on and mode is LIVE."""
        return (
            self.trading_mode == "LIVE"
            and self.enable_live_trading
            and self.capital_mode_confirmed
            and self.risk_controls_validated
            and self.execution_path_validated
            and self.security_hardening_validated
        )

    def validate(self) -> None:
        """Validate capital mode prerequisites and risk parameter bounds.

        In PAPER mode: validates risk bounds only (no gate check).
        In LIVE mode: validates ALL five gates and risk bounds.

        Raises:
            CapitalModeGuardError: Any gate missing for LIVE mode.
            ValueError: Risk parameter out of safe bounds.
        """
        self._validate_risk_bounds()

        if self.trading_mode == "LIVE":
            missing = self._missing_gates()
            if missing:
                raise CapitalModeGuardError(
                    f"Capital mode (LIVE) requires all gates enabled. "
                    f"Missing: {', '.join(missing)}. "
                    f"Set each env var to 'true' only after the corresponding "
                    f"SENTINEL MAJOR validation sweep is approved."
                )

        log.info(
            "capital_mode_config_validated",
            trading_mode=self.trading_mode,
            capital_mode_allowed=self.is_capital_mode_allowed(),
        )

    def open_gates_report(self) -> dict[str, bool]:
        """Return gate status for operator visibility."""
        return {
            "enable_live_trading": self.enable_live_trading,
            "capital_mode_confirmed": self.capital_mode_confirmed,
            "risk_controls_validated": self.risk_controls_validated,
            "execution_path_validated": self.execution_path_validated,
            "security_hardening_validated": self.security_hardening_validated,
        }

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _missing_gates(self) -> list[str]:
        missing = []
        if not self.enable_live_trading:
            missing.append("ENABLE_LIVE_TRADING")
        if not self.capital_mode_confirmed:
            missing.append("CAPITAL_MODE_CONFIRMED")
        if not self.risk_controls_validated:
            missing.append("RISK_CONTROLS_VALIDATED")
        if not self.execution_path_validated:
            missing.append("EXECUTION_PATH_VALIDATED")
        if not self.security_hardening_validated:
            missing.append("SECURITY_HARDENING_VALIDATED")
        return missing

    def _validate_risk_bounds(self) -> None:
        if self.kelly_fraction != KELLY_FRACTION:
            raise ValueError(
                f"kelly_fraction must be {KELLY_FRACTION} (fractional Kelly only); "
                f"got {self.kelly_fraction}. Full Kelly (1.0) is FORBIDDEN."
            )
        if not (0.0 < self.max_position_fraction <= MAX_POSITION_FRACTION_CAP):
            raise ValueError(
                f"max_position_fraction must be in (0, {MAX_POSITION_FRACTION_CAP}]; "
                f"got {self.max_position_fraction}"
            )
        if self.daily_loss_limit_usd >= 0:
            raise ValueError(
                f"daily_loss_limit_usd must be negative; got {self.daily_loss_limit_usd}"
            )
        if not (0.0 < self.drawdown_limit_pct <= DRAWDOWN_LIMIT_CAP):
            raise ValueError(
                f"drawdown_limit_pct must be in (0, {DRAWDOWN_LIMIT_CAP}]; "
                f"got {self.drawdown_limit_pct}"
            )
        if self.min_liquidity_usd < 0:
            raise ValueError(
                f"min_liquidity_usd must be >= 0; got {self.min_liquidity_usd}"
            )


# ── Module helpers ────────────────────────────────────────────────────────────


def _flag(env_var: str) -> bool:
    return os.getenv(env_var, "false").strip().lower() == "true"


def _parse_float(env_var: str, default: float) -> float:
    raw = os.getenv(env_var, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        log.warning("capital_mode_config_parse_float_failed", env_var=env_var, raw=raw, default=default)
        return default
