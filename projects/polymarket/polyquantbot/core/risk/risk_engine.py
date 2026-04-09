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
        state_file: str | None = None,
        require_state_on_startup: bool = False,
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
        self._persistence_block_reason: str | None = None
        configured_path = state_file or os.getenv(
            "POLYQUANT_RISK_ENGINE_STATE_FILE",
            "projects/polymarket/polyquantbot/infra/risk_engine_state.json",
        )
        self._state_file = Path(configured_path)
        self._state_marker_file = self._state_file.with_suffix(f"{self._state_file.suffix}.initialized")
        self._require_state_on_startup = require_state_on_startup
        self._load_state()

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
        self._persist_state()
        return self.get_state()

    def record_trade_pnl(self, pnl: float) -> RiskState:
        today_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._daily_pnl_by_day[today_key] = self._daily_pnl_by_day.get(today_key, 0.0) + float(pnl)
        self._refresh_global_block()
        self._persist_state()
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

    def as_dict(self) -> dict[str, float | int | bool | str]:
        state = self.get_state()
        payload: dict[str, float | int | bool | str] = {
            "equity": state.equity,
            "portfolio_pnl": state.portfolio_pnl,
            "drawdown_ratio": state.drawdown_ratio,
            "daily_loss": state.daily_loss,
            "open_trades": state.open_trades,
            "correlated_exposure_ratio": state.correlated_exposure_ratio,
            "global_trade_block": state.global_trade_block,
        }
        if self._persistence_block_reason is not None:
            payload["persistence_block_reason"] = self._persistence_block_reason
        return payload

    def _refresh_global_block(self) -> None:
        state = self.get_state()
        self._global_trade_block = (
            state.drawdown_ratio > self._max_drawdown_ratio
            or state.daily_loss <= self._daily_loss_limit
        )
        if self._persistence_block_reason is not None:
            self._global_trade_block = True

    def _load_state(self) -> None:
        if not self._state_file.exists():
            marker_exists = self._state_marker_file.exists()
            if self._require_state_on_startup or marker_exists:
                self._persistence_block_reason = "risk_state_missing_on_startup"
                self._refresh_global_block()
            return
        try:
            payload = json.loads(self._state_file.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            self._persistence_block_reason = "risk_state_unreadable_on_startup"
            self._refresh_global_block()
            log.error("risk_engine_restore_failed", state_file=str(self._state_file), error=str(exc))
            return

        if not isinstance(payload, dict):
            self._persistence_block_reason = "risk_state_invalid_payload_on_startup"
            self._refresh_global_block()
            log.error(
                "risk_engine_restore_failed",
                state_file=str(self._state_file),
                error="invalid_payload_type",
            )
            return

        try:
            self._peak_equity = max(float(payload.get("peak_equity", 0.0)), 0.0)
            self._equity = float(payload.get("equity", 0.0))
            self._portfolio_pnl = float(payload.get("portfolio_pnl", 0.0))
            self._drawdown_ratio = max(float(payload.get("drawdown_ratio", 0.0)), 0.0)
            self._daily_pnl_by_day = {
                str(key): float(value)
                for key, value in (payload.get("daily_pnl_by_day") or {}).items()
            }
            self._open_trades = max(int(payload.get("open_trades", 0)), 0)
            self._correlated_exposure_ratio = max(float(payload.get("correlated_exposure_ratio", 0.0)), 0.0)
            self._global_trade_block = bool(payload.get("global_trade_block", False))
            self._persistence_block_reason = None
            self._refresh_global_block()
            log.info(
                "risk_engine_state_restored",
                state_file=str(self._state_file),
                global_trade_block=self._global_trade_block,
            )
        except Exception as exc:  # noqa: BLE001
            self._persistence_block_reason = "risk_state_corrupt_on_startup"
            self._refresh_global_block()
            log.error("risk_engine_restore_failed", state_file=str(self._state_file), error=str(exc))

    def _persist_state(self) -> None:
        payload = {
            "peak_equity": self._peak_equity,
            "equity": self._equity,
            "portfolio_pnl": self._portfolio_pnl,
            "drawdown_ratio": self._drawdown_ratio,
            "daily_pnl_by_day": self._daily_pnl_by_day,
            "open_trades": self._open_trades,
            "correlated_exposure_ratio": self._correlated_exposure_ratio,
            "global_trade_block": self._global_trade_block,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            self._state_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            self._state_marker_file.write_text("initialized\n", encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            self._persistence_block_reason = "risk_state_persist_failed"
            self._refresh_global_block()
            log.error("risk_engine_persist_failed", state_file=str(self._state_file), error=str(exc))
