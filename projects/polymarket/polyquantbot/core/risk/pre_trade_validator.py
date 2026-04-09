from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PreTradeValidationResult:
    decision: str
    reason: str
    checks: dict[str, float | bool]


class PreTradeValidator:
    """Deterministic hard-block validator for execution readiness."""

    def __init__(
        self,
        *,
        min_liquidity_usd: float = 10_000.0,
        max_spread: float = 0.04,
        max_position_size_ratio: float = 0.10,
        max_concurrent_trades: int = 5,
        max_correlated_exposure_ratio: float = 0.40,
        max_drawdown_ratio: float = 0.08,
        daily_loss_limit: float = -2_000.0,
    ) -> None:
        self._min_liquidity_usd = min_liquidity_usd
        self._max_spread = max_spread
        self._max_position_size_ratio = max_position_size_ratio
        self._max_concurrent_trades = max_concurrent_trades
        self._max_correlated_exposure_ratio = max_correlated_exposure_ratio
        self._max_drawdown_ratio = max_drawdown_ratio
        self._daily_loss_limit = daily_loss_limit

    def validate(
        self,
        *,
        signal_data: dict[str, Any],
        decision_data: dict[str, Any],
        risk_state: dict[str, Any],
    ) -> PreTradeValidationResult:
        expected_value = float(signal_data.get("expected_value", 0.0))
        edge = float(signal_data.get("edge", 0.0))
        liquidity = float(signal_data.get("liquidity_usd", 0.0))
        spread = float(signal_data.get("spread", 0.0))
        position_size = max(float(decision_data.get("position_size", 0.0)), 0.0)
        portfolio_equity = max(float(risk_state.get("equity", 0.0)), 0.0)
        max_position_allowed = portfolio_equity * self._max_position_size_ratio
        concurrent_trades = int(risk_state.get("open_trades", 0))
        correlated_exposure = max(float(risk_state.get("correlated_exposure_ratio", 0.0)), 0.0)
        drawdown_ratio = max(float(risk_state.get("drawdown_ratio", 0.0)), 0.0)
        daily_loss = float(risk_state.get("daily_loss", 0.0))
        global_trade_block = bool(risk_state.get("global_trade_block", False))

        checks: dict[str, float | bool] = {
            "expected_value": expected_value,
            "edge": edge,
            "liquidity_usd": liquidity,
            "spread": spread,
            "position_size": position_size,
            "max_position_allowed": max_position_allowed,
            "open_trades": concurrent_trades,
            "correlated_exposure_ratio": correlated_exposure,
            "drawdown_ratio": drawdown_ratio,
            "daily_loss": daily_loss,
            "global_trade_block": global_trade_block,
        }

        if global_trade_block:
            return PreTradeValidationResult("BLOCK", "global_trade_block_active", checks)
        if expected_value <= 0.0:
            return PreTradeValidationResult("BLOCK", "ev_non_positive", checks)
        if edge <= 0.0:
            return PreTradeValidationResult("BLOCK", "edge_non_positive", checks)
        if liquidity < self._min_liquidity_usd:
            return PreTradeValidationResult("BLOCK", "liquidity_below_threshold", checks)
        if spread > self._max_spread:
            return PreTradeValidationResult("BLOCK", "spread_above_threshold", checks)
        if position_size <= 0.0 or (max_position_allowed > 0.0 and position_size > max_position_allowed):
            return PreTradeValidationResult("BLOCK", "position_size_limit_exceeded", checks)
        if concurrent_trades >= self._max_concurrent_trades:
            return PreTradeValidationResult("BLOCK", "max_concurrent_trades_exceeded", checks)
        if correlated_exposure > self._max_correlated_exposure_ratio:
            return PreTradeValidationResult("BLOCK", "correlated_exposure_exceeded", checks)
        if daily_loss <= self._daily_loss_limit:
            return PreTradeValidationResult("BLOCK", "daily_loss_limit_breached", checks)
        if drawdown_ratio > self._max_drawdown_ratio:
            return PreTradeValidationResult("BLOCK", "max_drawdown_breached", checks)
        return PreTradeValidationResult("ALLOW", "passed", checks)
