from __future__ import annotations

import datetime
import os
from dataclasses import dataclass
from typing import Any, Optional

import structlog

from ..core.ledger import LedgerAction, TradeLedger
from ..core.positions import PaperPositionManager
from ..core.wallet_engine import WalletEngine

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class GuardrailConfig:
    max_position_size_per_trade_pct: float
    max_total_exposure_pct: float
    max_open_positions: int
    daily_loss_limit_pct: float


@dataclass(frozen=True)
class GuardrailViolation:
    outcome: str
    reason: str
    details: dict[str, Any]


class CapitalGuard:
    """Execution-boundary safety guard for capital and exposure protection."""

    def __init__(
        self,
        wallet: WalletEngine,
        positions: PaperPositionManager,
        ledger: TradeLedger,
        config: Optional[GuardrailConfig] = None,
    ) -> None:
        self._wallet = wallet
        self._positions = positions
        self._ledger = ledger
        self._config = config or GuardrailConfig(
            max_position_size_per_trade_pct=float(
                os.environ.get("MAX_POSITION_SIZE_PER_TRADE_PCT", "0.10")
            ),
            max_total_exposure_pct=float(
                os.environ.get("MAX_TOTAL_EXPOSURE_PCT", "0.50")
            ),
            max_open_positions=int(os.environ.get("MAX_OPEN_POSITIONS", "5")),
            daily_loss_limit_pct=float(os.environ.get("DAILY_LOSS_LIMIT_PCT", "0.08")),
        )
        self._peak_equity: float = wallet.get_state().equity

    def evaluate(self, order: dict[str, Any]) -> Optional[GuardrailViolation]:
        """Return a violation when execution must be blocked, else ``None``."""
        wallet_state = self._wallet.get_state()
        equity = max(wallet_state.equity, 0.0001)
        self._peak_equity = max(self._peak_equity, equity)

        order_size = float(order.get("size", 0.0))
        market_id = str(order.get("market_id", ""))
        current_exposure = self._current_exposure()

        max_trade_size = equity * self._config.max_position_size_per_trade_pct
        if order_size > max_trade_size:
            return GuardrailViolation(
                outcome="blocked",
                reason="capital_insufficient",
                details={
                    "requested_size": order_size,
                    "max_position_size_per_trade": round(max_trade_size, 4),
                    "equity": round(equity, 4),
                },
            )

        if wallet_state.cash < order_size:
            return GuardrailViolation(
                outcome="blocked",
                reason="capital_insufficient",
                details={
                    "requested_size": order_size,
                    "available_cash": round(wallet_state.cash, 4),
                },
            )

        projected_exposure = current_exposure + order_size
        max_total_exposure = equity * self._config.max_total_exposure_pct
        if projected_exposure > max_total_exposure:
            return GuardrailViolation(
                outcome="blocked",
                reason="exposure_limit",
                details={
                    "current_exposure": round(current_exposure, 4),
                    "projected_exposure": round(projected_exposure, 4),
                    "max_total_exposure": round(max_total_exposure, 4),
                    "max_total_exposure_pct": self._config.max_total_exposure_pct,
                },
            )

        open_positions = self._positions.get_all_open()
        market_already_open = any(p.market_id == market_id for p in open_positions)
        if len(open_positions) >= self._config.max_open_positions and not market_already_open:
            return GuardrailViolation(
                outcome="blocked",
                reason="max_positions_reached",
                details={
                    "open_positions": len(open_positions),
                    "max_open_positions": self._config.max_open_positions,
                },
            )

        daily_realized_loss = self._daily_realized_loss_utc()
        daily_loss_ratio = daily_realized_loss / equity
        drawdown_ratio = (self._peak_equity - equity) / self._peak_equity if self._peak_equity > 0 else 0.0
        if (
            daily_loss_ratio >= self._config.daily_loss_limit_pct
            or drawdown_ratio >= self._config.daily_loss_limit_pct
        ):
            return GuardrailViolation(
                outcome="blocked",
                reason="drawdown_limit",
                details={
                    "daily_realized_loss": round(daily_realized_loss, 4),
                    "daily_loss_ratio": round(daily_loss_ratio, 6),
                    "drawdown_ratio": round(drawdown_ratio, 6),
                    "limit_pct": self._config.daily_loss_limit_pct,
                },
            )

        return None

    def _current_exposure(self) -> float:
        """Compute current open-position exposure at execution time."""
        return round(sum(position.size for position in self._positions.get_all_open()), 4)

    def _daily_realized_loss_utc(self) -> float:
        """Compute absolute realized loss for the current UTC day."""
        today = datetime.datetime.now(datetime.timezone.utc).date()
        loss_total = 0.0
        for entry in self._ledger.get_all():
            if entry.action != LedgerAction.CLOSE or entry.realized_pnl is None:
                continue
            if entry.realized_pnl >= 0:
                continue
            entry_date = self._parse_ledger_date(entry.timestamp)
            if entry_date == today:
                loss_total += abs(entry.realized_pnl)
        return round(loss_total, 4)

    @staticmethod
    def _parse_ledger_date(timestamp: str) -> Optional[datetime.date]:
        if not timestamp:
            return None
        try:
            normalized = timestamp.replace("Z", "+00:00")
            return datetime.datetime.fromisoformat(normalized).astimezone(datetime.timezone.utc).date()
        except ValueError:
            log.warning("capital_guard_invalid_ledger_timestamp", timestamp=timestamp)
            return None
