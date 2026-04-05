from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Protocol, TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from ...core.portfolio.pnl import PnLTracker
    from ...core.wallet_engine import WalletEngine
    from ...core.positions import PaperPositionManager

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class PortfolioPosition:
    market_id: str
    side: str
    avg_price: float
    size: float
    unrealized_pnl: float


@dataclass(frozen=True)
class PortfolioState:
    positions: tuple[PortfolioPosition, ...]
    equity: float
    cash: float
    pnl: float


class _WalletStateProtocol(Protocol):
    cash: float
    equity: float


class PortfolioService:
    """Single source of truth for Telegram portfolio views.

    Aggregates wallet, positions, and pnl into an immutable snapshot so all
    Telegram views render from the same state in a single read.
    """

    def __init__(self) -> None:
        self._wallet_engine: Optional["WalletEngine"] = None
        self._position_manager: Optional["PaperPositionManager"] = None
        self._pnl_tracker: Optional["PnLTracker"] = None
        self._sim_positions: list[PortfolioPosition] = []
        self._sim_cash: float = 0.0
        self._sim_equity: float = 0.0
        self._sim_realized_pnl: float = 0.0

    def set_wallet_engine(self, wallet_engine: "WalletEngine") -> None:
        self._wallet_engine = wallet_engine
        log.info("portfolio_service_wallet_engine_injected")

    def set_position_manager(self, position_manager: "PaperPositionManager") -> None:
        self._position_manager = position_manager
        log.info("portfolio_service_position_manager_injected")

    def set_pnl_tracker(self, pnl_tracker: "PnLTracker") -> None:
        self._pnl_tracker = pnl_tracker
        log.info("portfolio_service_pnl_tracker_injected")


    def update_simulated_state(
        self,
        positions: list[dict[str, Any]],
        cash: float,
        equity: float,
        realized_pnl: float,
    ) -> None:
        """Update paper-simulation snapshot for execution-engine-only mode."""
        normalized: list[PortfolioPosition] = []
        for pos in positions:
            normalized.append(
                PortfolioPosition(
                    market_id=str(pos.get("market_id", "")),
                    side=str(pos.get("side", "")),
                    avg_price=float(pos.get("entry_price", pos.get("avg_price", 0.0)) or 0.0),
                    size=float(pos.get("size", 0.0) or 0.0),
                    unrealized_pnl=float(pos.get("pnl", pos.get("unrealized_pnl", 0.0)) or 0.0),
                )
            )
        self._sim_positions = normalized
        self._sim_cash = float(cash)
        self._sim_equity = float(equity)
        self._sim_realized_pnl = float(realized_pnl)
        log.info("portfolio_service_simulated_state_updated", positions=len(normalized), equity=self._sim_equity)

    def get_state(self) -> Optional[PortfolioState]:
        """Return immutable portfolio snapshot or ``None`` when unavailable.

        Returns ``None`` for partial/inconsistent payloads so view handlers can
        safely show a single fallback message instead of mismatched values.
        """
        if self._wallet_engine is None or self._position_manager is None or self._pnl_tracker is None:
            if self._sim_equity > 0.0:
                return PortfolioState(
                    positions=tuple(self._sim_positions),
                    equity=self._sim_equity,
                    cash=self._sim_cash,
                    pnl=self._sim_realized_pnl + sum(p.unrealized_pnl for p in self._sim_positions),
                )
            log.warning(
                "portfolio_service_not_ready",
                has_wallet=self._wallet_engine is not None,
                has_positions=self._position_manager is not None,
                has_pnl=self._pnl_tracker is not None,
            )
            return None

        try:
            wallet_state: _WalletStateProtocol = self._wallet_engine.get_state()
            raw_positions = self._position_manager.get_all_open()
            pnl_summary = self._pnl_tracker.summary()
        except Exception as exc:
            log.error("portfolio_service_snapshot_error", error=str(exc))
            return None

        if wallet_state is None or raw_positions is None or pnl_summary is None:
            log.warning("portfolio_service_partial_snapshot")
            return None

        positions: list[PortfolioPosition] = []
        try:
            for pos in raw_positions:
                market_id = str(getattr(pos, "market_id", ""))
                side = str(getattr(pos, "side", ""))
                size = float(getattr(pos, "size", 0.0))
                avg_price = float(
                    getattr(pos, "avg_price", getattr(pos, "entry_price", 0.0))
                )
                unrealized_pnl = float(getattr(pos, "unrealized_pnl", 0.0))
                if not market_id or not side:
                    log.warning("portfolio_service_position_partial", position=repr(pos))
                    return None
                positions.append(
                    PortfolioPosition(
                        market_id=market_id,
                        side=side,
                        avg_price=avg_price,
                        size=size,
                        unrealized_pnl=unrealized_pnl,
                    )
                )
        except Exception as exc:
            log.error("portfolio_service_positions_normalization_error", error=str(exc))
            return None

        total_pnl = float(pnl_summary.get("total_pnl", 0.0))
        return PortfolioState(
            positions=tuple(positions),
            equity=float(wallet_state.equity),
            cash=float(wallet_state.cash),
            pnl=total_pnl,
        )


_portfolio_service = PortfolioService()


def get_portfolio_service() -> PortfolioService:
    return _portfolio_service
