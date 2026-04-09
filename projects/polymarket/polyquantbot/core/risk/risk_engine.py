from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


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
        persistence_path: str | None = None,
    ) -> None:
        self._max_drawdown_ratio = max_drawdown_ratio
        self._daily_loss_limit = daily_loss_limit
        self._persistence_path = Path(persistence_path) if persistence_path else None
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
        self.persist_state()
        return self.get_state()

    def record_trade_pnl(self, pnl: float) -> RiskState:
        today_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._daily_pnl_by_day[today_key] = self._daily_pnl_by_day.get(today_key, 0.0) + float(pnl)
        self._refresh_global_block()
        self.persist_state()
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

    def persist_state(self) -> tuple[bool, str]:
        if self._persistence_path is None:
            return True, "persistence_disabled"
        payload = self._serialize_state()
        temporary_path = self._persistence_path.with_suffix(f"{self._persistence_path.suffix}.tmp")
        try:
            self._persistence_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            temporary_path.replace(self._persistence_path)
            return True, "persisted"
        except OSError as exc:
            return False, f"persist_write_error:{exc.__class__.__name__}"

    def restore_state(self) -> tuple[bool, str]:
        if self._persistence_path is None:
            return False, "persistence_path_missing"
        try:
            content = self._persistence_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return False, "persistence_missing"
        except OSError as exc:
            return False, f"persistence_unreadable:{exc.__class__.__name__}"
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            return False, "persistence_corrupt_json"
        validated = self._validate_payload(payload)
        if validated is None:
            return False, "persistence_invalid_structure"
        self._peak_equity = validated["peak_equity"]
        self._equity = validated["equity"]
        self._portfolio_pnl = validated["portfolio_pnl"]
        self._drawdown_ratio = validated["drawdown_ratio"]
        self._daily_pnl_by_day = validated["daily_pnl_by_day"]
        self._open_trades = validated["open_trades"]
        self._correlated_exposure_ratio = validated["correlated_exposure_ratio"]
        self._global_trade_block = validated["global_trade_block"]
        self._refresh_global_block()
        return True, "restored"

    def _serialize_state(self) -> dict[str, Any]:
        return {
            "version": 1,
            "peak_equity": self._peak_equity,
            "equity": self._equity,
            "portfolio_pnl": self._portfolio_pnl,
            "drawdown_ratio": self._drawdown_ratio,
            "daily_pnl_by_day": dict(self._daily_pnl_by_day),
            "open_trades": self._open_trades,
            "correlated_exposure_ratio": self._correlated_exposure_ratio,
            "global_trade_block": self._global_trade_block,
        }

    def _validate_payload(self, payload: object) -> dict[str, Any] | None:
        if not isinstance(payload, dict):
            return None
        required_scalar_fields = (
            "peak_equity",
            "equity",
            "portfolio_pnl",
            "drawdown_ratio",
            "open_trades",
            "correlated_exposure_ratio",
            "global_trade_block",
        )
        for field in required_scalar_fields:
            if field not in payload:
                return None
        daily_pnl_by_day = payload.get("daily_pnl_by_day")
        if not isinstance(daily_pnl_by_day, dict):
            return None
        validated_daily: dict[str, float] = {}
        for day_key, day_value in daily_pnl_by_day.items():
            if not isinstance(day_key, str):
                return None
            try:
                validated_daily[day_key] = float(day_value)
            except (TypeError, ValueError):
                return None
        try:
            return {
                "peak_equity": float(payload["peak_equity"]),
                "equity": float(payload["equity"]),
                "portfolio_pnl": float(payload["portfolio_pnl"]),
                "drawdown_ratio": float(payload["drawdown_ratio"]),
                "daily_pnl_by_day": validated_daily,
                "open_trades": int(payload["open_trades"]),
                "correlated_exposure_ratio": float(payload["correlated_exposure_ratio"]),
                "global_trade_block": bool(payload["global_trade_block"]),
            }
        except (TypeError, ValueError):
            return None
