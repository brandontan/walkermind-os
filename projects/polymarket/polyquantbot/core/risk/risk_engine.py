from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class RiskState:
    equity: float
    portfolio_pnl: float
    drawdown_ratio: float
    daily_loss: float
    open_trades: int
    correlated_exposure_ratio: float
    global_trade_block: bool


class RiskEngine:
    """System-level risk state tracker with hard global block enforcement."""

    def __init__(
        self,
        *,
        max_drawdown_ratio: float = 0.08,
        daily_loss_limit: float = -2_000.0,
    ) -> None:
        self._max_drawdown_ratio = max_drawdown_ratio
        self._daily_loss_limit = daily_loss_limit
        self._peak_equity = 0.0
        self._equity = 0.0
        self._portfolio_pnl = 0.0
        self._drawdown_ratio = 0.0
        self._daily_pnl_by_day: dict[str, float] = {}
        self._open_trades = 0
        self._correlated_exposure_ratio = 0.0
        self._global_trade_block = False

    def update_from_snapshot(
        self,
        *,
        equity: float,
        realized_pnl: float,
        open_trades: int,
        correlated_exposure_ratio: float,
    ) -> RiskState:
        self._equity = float(equity)
        self._portfolio_pnl = float(realized_pnl)
        self._open_trades = max(int(open_trades), 0)
        self._correlated_exposure_ratio = max(float(correlated_exposure_ratio), 0.0)
        if self._peak_equity <= 0.0:
            self._peak_equity = self._equity
        self._peak_equity = max(self._peak_equity, self._equity)
        if self._peak_equity > 0.0:
            self._drawdown_ratio = max((self._peak_equity - self._equity) / self._peak_equity, 0.0)
        else:
            self._drawdown_ratio = 0.0
        self._refresh_global_block()
        return self.get_state()

    def record_trade_pnl(self, pnl: float) -> RiskState:
        today_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._daily_pnl_by_day[today_key] = self._daily_pnl_by_day.get(today_key, 0.0) + float(pnl)
        self._refresh_global_block()
        return self.get_state()

    def get_state(self) -> RiskState:
        today_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        daily_loss = min(self._daily_pnl_by_day.get(today_key, 0.0), 0.0)
        return RiskState(
            equity=self._equity,
            portfolio_pnl=self._portfolio_pnl,
            drawdown_ratio=self._drawdown_ratio,
            daily_loss=daily_loss,
            open_trades=self._open_trades,
            correlated_exposure_ratio=self._correlated_exposure_ratio,
            global_trade_block=self._global_trade_block,
        )

    def as_dict(self) -> dict[str, float | int | bool]:
        state = self.get_state()
        return {
            "equity": state.equity,
            "portfolio_pnl": state.portfolio_pnl,
            "drawdown_ratio": state.drawdown_ratio,
            "daily_loss": state.daily_loss,
            "open_trades": state.open_trades,
            "correlated_exposure_ratio": state.correlated_exposure_ratio,
            "global_trade_block": state.global_trade_block,
        }

    def _refresh_global_block(self) -> None:
        state = self.get_state()
        self._global_trade_block = (
            state.drawdown_ratio > self._max_drawdown_ratio
            or state.daily_loss <= self._daily_loss_limit
        )
