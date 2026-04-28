"""Live execution control — deterministic guard and rollback for CrusaderBot.

LiveExecutionGuard is the single entry point that must be passed before any
live-mode execution path runs.  It enforces all five capital gates, validates
that a real WalletFinancialProvider is present (not a stub with zero-valued
fields), and logs a structured reason for every block.

RollbackState + disable_live_execution() provide the rollback/disable path
that operators and test harnesses can invoke to deterministically halt live
execution and log the reason.  Once disabled, re-enable requires explicit
operator action (re-setting kill_switch=False + re-validating gates).

Usage::

    guard = LiveExecutionGuard(config=CapitalModeConfig.from_env())
    guard.check(state, provider=my_provider)  # raises LiveExecutionBlockedError on fail

    # Emergency halt
    disable_live_execution(state, reason="operator_kill")
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

import structlog

from projects.polymarket.polyquantbot.server.config.capital_mode_config import (
    CapitalModeConfig,
    CapitalModeGuardError,
)
from projects.polymarket.polyquantbot.server.core.public_beta_state import PublicBetaState
from projects.polymarket.polyquantbot.server.risk.capital_risk_gate import WalletFinancialProvider

log = structlog.get_logger(__name__)

# Sentinel wallet ID used when checking provider readiness without a real wallet
_STUB_WALLET_ID: str = "__readiness_probe__"

# Threshold below which all-zero financial fields are treated as stub/uninitialized
_FINANCIAL_FIELD_ZERO_THRESHOLD: float = 1e-9


class LiveExecutionBlockedError(Exception):
    """Raised when live execution is attempted but a safety gate blocks it.

    Attributes:
        reason: Machine-readable block reason for structured logging.
    """

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"Live execution blocked [{reason}]: {detail}" if detail else f"Live execution blocked [{reason}]")


@dataclass
class RollbackState:
    """Snapshot of a rollback/disable event for audit trail.

    Attributes:
        reason:      Machine-readable reason for the disable.
        detail:      Human-readable detail (operator note, error message, etc.).
        disabled_at: UTC timestamp of when the disable was triggered.
        prior_kill_switch: Previous kill_switch state before rollback.
    """

    reason: str
    detail: str = ""
    disabled_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    prior_kill_switch: bool = False


def disable_live_execution(
    state: PublicBetaState,
    reason: str,
    detail: str = "",
) -> RollbackState:
    """Deterministically disable live execution and log the reason.

    Sets kill_switch=True on STATE so all downstream risk gates immediately
    reject new signals.  Returns a RollbackState audit record.

    Args:
        state:  Live PublicBetaState to mutate.
        reason: Machine-readable block reason (logged as structured field).
        detail: Optional human-readable context.

    Returns:
        RollbackState snapshot of the disable event.
    """
    prior = state.kill_switch
    state.kill_switch = True
    state.last_risk_reason = f"rollback:{reason}"
    rollback = RollbackState(
        reason=reason,
        detail=detail,
        prior_kill_switch=prior,
    )
    log.warning(
        "live_execution_disabled",
        reason=reason,
        detail=detail,
        prior_kill_switch=prior,
        kill_switch_now=True,
    )
    return rollback


class LiveExecutionGuard:
    """Pre-execution safety gate for all live execution paths.

    Checks in order:
      1. STATE.kill_switch — immediate block, no gate check needed
      2. STATE.mode == "live" — block if paper mode
      3. ENABLE_LIVE_TRADING env var — must be "true"
      4. CapitalModeConfig.validate() — all 5 gates must be on in LIVE mode
      5. WalletFinancialProvider zero-field check — provider must return real data

    All failures raise LiveExecutionBlockedError with a structured reason.
    Every block is logged at WARNING level with reason + detail fields.

    Args:
        config: CapitalModeConfig instance — supplies gate state and risk limits.
    """

    def __init__(self, config: CapitalModeConfig) -> None:
        self._config = config

    def check(
        self,
        state: PublicBetaState,
        provider: WalletFinancialProvider | None = None,
        wallet_id: str = _STUB_WALLET_ID,
    ) -> None:
        """Run all live execution safety checks.

        Args:
            state:     Live PublicBetaState.
            provider:  Optional WalletFinancialProvider — required for live mode.
            wallet_id: Wallet ID to probe for financial field readiness.

        Raises:
            LiveExecutionBlockedError: Any check fails.
        """
        # 1. Kill switch — first check, no gate verification
        if state.kill_switch:
            self._block("kill_switch_active", "kill_switch is set — live execution halted")

        # 2. Mode check — must be live to proceed
        if state.mode != "live":
            self._block(
                "mode_not_live",
                f"STATE.mode={state.mode!r} — live execution requires mode='live'",
            )

        # 3. ENABLE_LIVE_TRADING env var — belt-and-suspenders check independent of config
        if os.getenv("ENABLE_LIVE_TRADING", "").strip().lower() != "true":
            self._block(
                "enable_live_trading_not_set",
                "ENABLE_LIVE_TRADING env var is not 'true' — live execution requires explicit opt-in",
            )

        # 4. CapitalModeConfig gate validation
        try:
            self._config.validate()
        except CapitalModeGuardError as exc:
            self._block("capital_mode_guard_failed", str(exc))
        except ValueError as exc:
            self._block("capital_mode_config_invalid", str(exc))

        # 5. WalletFinancialProvider zero-field check — must be provided and non-zero
        if provider is None:
            self._block(
                "missing_financial_provider",
                "No WalletFinancialProvider injected — live execution requires real financial data",
            )

        # provider is not None past this point
        assert provider is not None  # narrowing for type checker

        balance = provider.get_balance_usd(wallet_id)
        exposure = provider.get_exposure_pct(wallet_id)
        drawdown = provider.get_drawdown_pct(wallet_id)

        if (
            abs(balance) < _FINANCIAL_FIELD_ZERO_THRESHOLD
            and abs(exposure) < _FINANCIAL_FIELD_ZERO_THRESHOLD
            and abs(drawdown) < _FINANCIAL_FIELD_ZERO_THRESHOLD
        ):
            self._block(
                "financial_provider_all_zero",
                "WalletFinancialProvider returned all-zero fields — "
                "this indicates a stub or uninitialized provider; real data is required for live execution",
            )

        log.info(
            "live_execution_guard_passed",
            mode=state.mode,
            kill_switch=state.kill_switch,
            trading_mode=self._config.trading_mode,
            capital_mode_allowed=self._config.is_capital_mode_allowed(),
            wallet_id=wallet_id,
        )

    def _block(self, reason: str, detail: str = "") -> None:
        log.warning(
            "live_execution_guard_blocked",
            reason=reason,
            detail=detail,
        )
        raise LiveExecutionBlockedError(reason=reason, detail=detail)
