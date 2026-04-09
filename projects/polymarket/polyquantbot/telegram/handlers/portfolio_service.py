from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Protocol, TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from ...core.portfolio.pnl import PnLTracker
    from ...core.wallet_engine import WalletEngine
    from ...core.positions import PaperPositionManager
    from ..execution.engine import ExecutionEngine

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class PortfolioPosition:
    market_id: str
    market_title: str
    side: str
    avg_price: float
    current_price: float
    size: float
    unrealized_pnl: float
    opened_at: str
    position_id: str


@dataclass(frozen=True)
class ClosedTrade:
    market_id: str
    market_title: str
    side: str
    entry_price: float
    exit_price: float
    pnl: float
    result: str
    closed_at: str
    position_id: str


@dataclass(frozen=True)
class PortfolioState:
    positions: tuple[PortfolioPosition, ...]
    closed_trades: tuple[ClosedTrade, ...]
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
        self._sim_closed_trades: list[ClosedTrade] = []
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

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        if value is None:
            return default
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped or stripped.lower() in {"n/a", "na", "none", "null", "nan", "-"}:
                return default
            value = stripped
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _normalize_positions(self, raw_positions: list[dict[str, Any]]) -> list[PortfolioPosition]:
        """Convert raw position dicts to PortfolioPosition objects."""
        normalized: list[PortfolioPosition] = []
        for pos in raw_positions:
            normalized.append(
                PortfolioPosition(
                    market_id=str(pos.get("market_id", "")),
                    market_title=str(pos.get("market_title", "")),
                    side=str(pos.get("side", "")),
                    avg_price=self._safe_float(pos.get("entry_price", pos.get("avg_price", 0.0)), 0.0),
                    current_price=self._safe_float(pos.get("current_price", pos.get("entry_price", pos.get("avg_price", 0.0))), 0.0),
                    size=self._safe_float(pos.get("size", 0.0), 0.0),
                    unrealized_pnl=self._safe_float(pos.get("pnl", pos.get("unrealized_pnl", 0.0)), 0.0),
                    opened_at=str(pos.get("opened_at", "")),
                    position_id=str(pos.get("position_id", pos.get("market_id", ""))),
                )
            )
        return normalized

    def _normalize_closed_trades(self, raw_trades: list[dict[str, Any]]) -> list[ClosedTrade]:
        normalized: list[ClosedTrade] = []
        for trade in raw_trades:
            normalized.append(
                ClosedTrade(
                    market_id=str(trade.get("market_id", "")),
                    market_title=str(trade.get("market_title", "")),
                    side=str(trade.get("side", "")),
                    entry_price=self._safe_float(trade.get("entry_price", trade.get("avg_price", 0.0)), 0.0),
                    exit_price=self._safe_float(trade.get("exit_price", trade.get("close_price", 0.0)), 0.0),
                    pnl=self._safe_float(trade.get("pnl", 0.0), 0.0),
                    result=str(trade.get("result", "")),
                    closed_at=str(trade.get("closed_at", "")),
                    position_id=str(trade.get("position_id", trade.get("market_id", ""))),
                )
            )
        return normalized

    def merge_execution_state(
        self,
        positions: list[dict[str, Any]],
        closed_trades: list[dict[str, Any]],
        cash: float,
        equity: float,
        realized_pnl: float,
    ) -> None:
        """Merge execution state without overwriting existing data."""
        if equity > 0:
            self._sim_positions = self._normalize_positions(positions)
            self._sim_closed_trades = self._normalize_closed_trades(closed_trades)
            self._sim_cash = cash
            self._sim_equity = equity
            self._sim_realized_pnl = realized_pnl
            log.info(
                "portfolio_service_execution_state_merged",
                positions=len(self._sim_positions),
                closed_trades=len(self._sim_closed_trades),
                equity=equity,
            )

    def update_simulated_state(
        self,
        positions: list[dict[str, Any]],
        closed_trades: list[dict[str, Any]],
        cash: float,
        equity: float,
        realized_pnl: float,
    ) -> None:
        """Update paper-simulation snapshot for execution-engine-only mode."""
        self._sim_positions = self._normalize_positions(positions)
        self._sim_closed_trades = self._normalize_closed_trades(closed_trades)
        self._sim_cash = cash
        self._sim_equity = equity
        self._sim_realized_pnl = realized_pnl
        log.info(
            "portfolio_service_simulated_state_updated",
            positions=len(self._sim_positions),
            closed_trades=len(self._sim_closed_trades),
            equity=equity,
        )

    def get_state(self) -> Optional[PortfolioState]:
        """Return immutable portfolio snapshot or ``None`` when unavailable.
        
        Returns ``None`` for partial/inconsistent payloads so view handlers can
        safely show a single fallback message instead of mismatched values.
        """
        if self._wallet_engine is None or self._position_manager is None or self._pnl_tracker is None:
            if self._sim_equity > 0.0:
                return PortfolioState(
                    positions=tuple(self._sim_positions),
                    closed_trades=tuple(self._sim_closed_trades),
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
                market_title = str(getattr(pos, "market_title", ""))
                side = str(getattr(pos, "side", ""))
                size = self._safe_float(getattr(pos, "size", 0.0), 0.0)
                avg_price = self._safe_float(
                    getattr(pos, "avg_price", getattr(pos, "entry_price", 0.0)),
                    0.0,
                )
                unrealized_pnl = self._safe_float(getattr(pos, "unrealized_pnl", 0.0), 0.0)
                current_price = self._safe_float(getattr(pos, "current_price", avg_price), avg_price)
                opened_at = str(getattr(pos, "opened_at", ""))
                position_id = str(getattr(pos, "position_id", market_id))
                if not market_id or not side:
                    log.warning("portfolio_service_position_partial", position=repr(pos))
                    return None
                positions.append(
                    PortfolioPosition(
                        market_id=market_id,
                        market_title=market_title,
                        side=side,
                        avg_price=avg_price,
                        current_price=current_price,
                        size=size,
                        unrealized_pnl=unrealized_pnl,
                        opened_at=opened_at,
                        position_id=position_id,
                    )
                )
        except Exception as exc:
            log.error("portfolio_service_positions_normalization_error", error=str(exc))
            return None

        total_pnl = self._safe_float(pnl_summary.get("total_pnl", 0.0), 0.0)
        return PortfolioState(
            positions=tuple(positions),
            closed_trades=tuple(self._sim_closed_trades),
            equity=self._safe_float(wallet_state.equity, 0.0),
            cash=self._safe_float(wallet_state.cash, 0.0),
            pnl=total_pnl,
        )


_portfolio_service = PortfolioService()


def get_portfolio_service() -> PortfolioService:
    return _portfolio_service


async def get_performance_view() -> dict[str, Any]:
    from ...execution.trade_trace import TradeTraceEngine
    from ...execution.engine import get_execution_engine
    
    engine = get_execution_engine()
    analytics = engine.get_analytics()
    trace_engine = TradeTraceEngine()
    summary = analytics.summary()
    traces = trace_engine.get_traces()

    return {
        "performance": {
            "trades": summary["trades"],
            "win_rate": f"{summary['win_rate']:.2f}",
            "avg_pnl": f"{summary['avg_pnl']:.2f}",
            "max_drawdown": f"{summary['max_drawdown']:.2f}",
        },
        "traces": [
            {
                "position_id": t.position_id,
                "score": t.intelligence_score,
                "threshold": t.decision_threshold,
                "action": t.action,
                "reasons": t.intelligence_reasons,
            }
            for t in traces[-5:]  # Last 5 traces
        ],
    }
