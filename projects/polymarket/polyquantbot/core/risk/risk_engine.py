from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path

import structlog


log = structlog.get_logger(__name__)


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
        block_state_file: str | None = None,
    ) -> None:
        self._max_drawdown_ratio = max_drawdown_ratio
        self._daily_loss_limit = daily_loss_limit
        self._block_state_file = Path(
            block_state_file
            or os.getenv(
                "POLYQUANT_RISK_BLOCK_STATE_FILE",
                "projects/polymarket/polyquantbot/infra/risk_global_block_state.json",
            )
        )
        self._peak_equity = 0.0
        self._equity = 0.0
        self._portfolio_pnl = 0.0
        self._drawdown_ratio = 0.0
        self._daily_pnl_by_day: dict[str, float] = {}
        self._open_trades = 0
        self._correlated_exposure_ratio = 0.0
        self._global_trade_block = False
        self._global_trade_block_reason = "not_blocked"
        self._state_load_failed = False
        self._load_persisted_block_state()

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

    def clear_global_trade_block(self) -> RiskState:
        """Explicit operator-clear path for sticky global block state."""
        self._global_trade_block = False
        self._global_trade_block_reason = "manual_clear"
        self._persist_block_state()
        return self.get_state()

    def _load_persisted_block_state(self) -> None:
        try:
            if not self._block_state_file.exists():
                return
            raw = self._block_state_file.read_text(encoding="utf-8")
            payload = json.loads(raw)
            persisted_block = bool(payload.get("global_trade_block", False))
            persisted_reason = str(payload.get("reason", "persisted_block_active"))
            if persisted_block:
                self._global_trade_block = True
                self._global_trade_block_reason = persisted_reason
                log.warning(
                    "risk_global_block_restored",
                    path=str(self._block_state_file),
                    reason=self._global_trade_block_reason,
                )
        except Exception as exc:  # noqa: BLE001
            self._state_load_failed = True
            self._global_trade_block = True
            self._global_trade_block_reason = "block_state_load_failed"
            log.error(
                "risk_global_block_restore_failed",
                path=str(self._block_state_file),
                error=str(exc),
            )

    def _persist_block_state(self) -> None:
        payload = {
            "global_trade_block": self._global_trade_block,
            "reason": self._global_trade_block_reason,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            self._block_state_file.parent.mkdir(parents=True, exist_ok=True)
            self._block_state_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            self._global_trade_block = True
            self._global_trade_block_reason = "block_state_persist_failed"
            log.error(
                "risk_global_block_persist_failed",
                path=str(self._block_state_file),
                error=str(exc),
            )

    def _refresh_global_block(self) -> None:
        state = self.get_state()
        risk_breached = state.drawdown_ratio > self._max_drawdown_ratio or state.daily_loss <= self._daily_loss_limit
        if self._state_load_failed:
            self._global_trade_block = True
            self._global_trade_block_reason = "block_state_load_failed"
            self._persist_block_state()
            return
        if risk_breached:
            self._global_trade_block = True
            if state.drawdown_ratio > self._max_drawdown_ratio:
                self._global_trade_block_reason = "max_drawdown_breached"
            else:
                self._global_trade_block_reason = "daily_loss_limit_breached"
        self._persist_block_state()
