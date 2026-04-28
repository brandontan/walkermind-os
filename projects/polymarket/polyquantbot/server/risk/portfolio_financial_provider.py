"""PortfolioFinancialProvider — WalletFinancialProvider backed by PublicBetaState.

This is the paper-mode implementation of WalletFinancialProvider that reads
financial fields from the live PublicBetaState (wallet_equity, exposure,
drawdown).

For live mode, a real market-data-backed provider must be built separately
(P8-C forward).  This provider raises MissingRealFinancialDataError if it
detects zero/stub values while running in live mode (STATE.mode == 'live'),
preventing silent fallback on real capital.

Usage (paper mode)::

    provider = PortfolioFinancialProvider(state=STATE)
    balance  = provider.get_balance_usd("wlc_abc")
    exposure = provider.get_exposure_pct("wlc_abc")
    drawdown = provider.get_drawdown_pct("wlc_abc")

Usage (live mode guard)::

    provider = PortfolioFinancialProvider(state=STATE)
    # Raises MissingRealFinancialDataError if wallet_equity == 0 in live mode
    balance = provider.get_balance_usd("wlc_abc")
"""
from __future__ import annotations

import structlog

from projects.polymarket.polyquantbot.server.core.public_beta_state import PublicBetaState

log = structlog.get_logger(__name__)

# Threshold below which equity is considered uninitialized / stub
_ZERO_THRESHOLD: float = 1e-9


class MissingRealFinancialDataError(Exception):
    """Raised when financial data is requested in live mode but STATE is zero/stub.

    This prevents live execution from silently proceeding with stale or
    uninitialized financial fields when real capital is at risk.
    """


class PortfolioFinancialProvider:
    """WalletFinancialProvider backed by PublicBetaState.

    In paper mode: returns STATE.wallet_equity, STATE.exposure, STATE.drawdown.
    In live mode: same, but raises MissingRealFinancialDataError if
    wallet_equity is effectively zero (stub/uninitialized).

    The wallet_id parameter is accepted for interface compatibility but is not
    used — in the paper model, STATE is the single-wallet truth.  A multi-wallet
    live implementation must replace this class.

    Args:
        state: Live PublicBetaState instance.
    """

    def __init__(self, state: PublicBetaState) -> None:
        self._state = state

    def get_balance_usd(self, wallet_id: str) -> float:
        """Return wallet equity (cash + locked) as USD balance.

        Args:
            wallet_id: Wallet identifier (logged; not used for lookup in paper mode).

        Returns:
            Current wallet equity from STATE.

        Raises:
            MissingRealFinancialDataError: live mode with zero equity.
        """
        self._assert_not_stub(wallet_id, field="balance_usd", value=self._state.wallet_equity)
        log.debug(
            "portfolio_financial_provider_balance",
            wallet_id=wallet_id,
            balance_usd=self._state.wallet_equity,
            mode=self._state.mode,
        )
        return self._state.wallet_equity

    def get_exposure_pct(self, wallet_id: str) -> float:
        """Return current exposure fraction from STATE.

        Args:
            wallet_id: Wallet identifier (logged; not used for lookup in paper mode).

        Returns:
            Current exposure as fraction (0.0–1.0) from STATE.
        """
        log.debug(
            "portfolio_financial_provider_exposure",
            wallet_id=wallet_id,
            exposure_pct=self._state.exposure,
            mode=self._state.mode,
        )
        return self._state.exposure

    def get_drawdown_pct(self, wallet_id: str) -> float:
        """Return current drawdown fraction from STATE.

        Args:
            wallet_id: Wallet identifier (logged; not used for lookup in paper mode).

        Returns:
            Current drawdown as fraction (0.0–1.0) from STATE.
        """
        log.debug(
            "portfolio_financial_provider_drawdown",
            wallet_id=wallet_id,
            drawdown_pct=self._state.drawdown,
            mode=self._state.mode,
        )
        return self._state.drawdown

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _assert_not_stub(self, wallet_id: str, field: str, value: float) -> None:
        """Raise MissingRealFinancialDataError if in live mode with zero value.

        In paper mode: zero equity is valid (fresh account with no trades).
        In live mode: zero equity indicates stub/uninitialized data and must
        be blocked before real capital is at risk.
        """
        if self._state.mode == "live" and abs(value) < _ZERO_THRESHOLD:
            detail = (
                f"PortfolioFinancialProvider.{field} returned {value!r} for wallet {wallet_id!r} "
                f"in live mode — this indicates stub or uninitialized state. "
                f"A real market-data-backed provider is required for live execution."
            )
            log.error(
                "portfolio_financial_provider_stub_in_live_mode",
                wallet_id=wallet_id,
                field=field,
                value=value,
                mode=self._state.mode,
            )
            raise MissingRealFinancialDataError(detail)
