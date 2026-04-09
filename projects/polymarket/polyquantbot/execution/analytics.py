from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import structlog

log = structlog.get_logger(__name__)


@dataclass
class TradeRecord:
    position_id: str
    pnl: float
    duration: float
    strategy_source: str
    regime_at_entry: str
    entry_quality: str
    entry_timing: str
    exit_reason: str
    theoretical_edge: float
    actual_return: float
    slippage_impact: float
    timing_effectiveness: float
    exit_efficiency: float


class PerformanceTracker:
    def __init__(self) -> None:
        self._trades: list[TradeRecord] = []
        self._equity_curve: list[float] = []

    @staticmethod
    def _value(payload: dict[str, Any], key: str, default: Any) -> Any:
        return payload.get(key, default)

    @staticmethod
    def _normalize_strategy(raw: object) -> str:
        candidate = str(raw or "UNKNOWN").strip().upper()
        return candidate if candidate in {"S1", "S2", "S3", "S5"} else "UNKNOWN"

    @staticmethod
    def _normalize_regime(raw: object) -> str:
        normalized = str(raw or "").strip().upper()
        mapping = {
            "NEWS_DRIVEN": "NEWS",
            "ARBITRAGE_DOMINANT": "ARBITRAGE",
            "SMART_MONEY_DOMINANT": "SMART_MONEY",
            "LOW_ACTIVITY_CHAOTIC": "CHAOTIC",
        }
        return mapping.get(normalized, normalized or "CHAOTIC")

    def record_trade(self, trade: dict[str, Any]) -> None:
        """Store trade details, prevent duplicates and handle edge cases."""
        position_id = str(self._value(trade, "position_id", "")).strip()
        if not position_id:
            log.warning("analytics_skip", reason="missing_position_id")
            return
        size = float(self._value(trade, "size", 0.0))
        if size <= 0:
            log.warning("analytics_skip", reason="size_zero_or_negative")
            return
        if any(t.position_id == position_id for t in self._trades):
            return  # Skip duplicates
        pnl = float(self._value(trade, "pnl", 0.0))
        theoretical_edge = max(0.0, float(self._value(trade, "theoretical_edge", 0.0)))
        actual_return = float(self._value(trade, "actual_return", pnl / size))
        duration = max(0.0, float(self._value(trade, "duration", 0.0)))
        self._trades.append(
            TradeRecord(
                position_id=position_id,
                pnl=pnl,
                duration=duration,
                strategy_source=self._normalize_strategy(self._value(trade, "strategy_source", "UNKNOWN")),
                regime_at_entry=self._normalize_regime(self._value(trade, "regime_at_entry", "CHAOTIC")),
                entry_quality=str(self._value(trade, "entry_quality", "not_provided")),
                entry_timing=str(self._value(trade, "entry_timing", "not_provided")),
                exit_reason=str(self._value(trade, "exit_reason", "not_provided")),
                theoretical_edge=theoretical_edge,
                actual_return=actual_return,
                slippage_impact=float(self._value(trade, "slippage_impact", 0.0)),
                timing_effectiveness=float(self._value(trade, "timing_effectiveness", 0.0)),
                exit_efficiency=float(self._value(trade, "exit_efficiency", 0.0)),
            )
        )
        self._update_equity_curve(pnl)

    def _update_equity_curve(self, pnl: float) -> None:
        """Track equity for drawdown calculation."""
        self._equity_curve.append(self._equity_curve[-1] + pnl if self._equity_curve else pnl)

    def _compute_risk_metrics(self) -> dict[str, float | int]:
        if not self._trades:
            return {"max_drawdown": 0.0, "avg_drawdown": 0.0, "loss_streak": 0}
        peaks: list[float] = []
        drawdowns: list[float] = []
        running_peak = float("-inf")
        for equity in self._equity_curve:
            running_peak = max(running_peak, equity)
            peaks.append(running_peak)
        for equity, peak in zip(self._equity_curve, peaks):
            if peak <= 0:
                drawdowns.append(0.0)
            else:
                drawdowns.append((peak - equity) / peak)
        max_dd = max(drawdowns) if drawdowns else 0.0
        avg_dd = sum(drawdowns) / len(drawdowns) if drawdowns else 0.0
        streak = 0
        max_streak = 0
        for trade in self._trades:
            if trade.pnl < 0:
                streak += 1
                max_streak = max(max_streak, streak)
            else:
                streak = 0
        return {
            "max_drawdown": round(max_dd, 6),
            "avg_drawdown": round(avg_dd, 6),
            "loss_streak": max_streak,
        }

    @staticmethod
    def _group_label_value() -> dict[str, float]:
        return {"total_pnl": 0.0, "trades": 0.0, "wins": 0.0, "total_return": 0.0}

    def _build_group_breakdown(self, group_field: str) -> dict[str, dict[str, float]]:
        grouped: dict[str, dict[str, float]] = {}
        for trade in self._trades:
            label = getattr(trade, group_field)
            row = grouped.setdefault(label, self._group_label_value())
            row["total_pnl"] += trade.pnl
            row["trades"] += 1.0
            row["wins"] += 1.0 if trade.pnl > 0 else 0.0
            row["total_return"] += trade.actual_return
        result: dict[str, dict[str, float]] = {}
        for label in sorted(grouped):
            row = grouped[label]
            trades = row["trades"] if row["trades"] > 0 else 1.0
            result[label] = {
                "pnl": round(row["total_pnl"], 6),
                "win_rate": round(row["wins"] / trades, 6),
                "avg_return": round(row["total_return"] / trades, 6),
            }
        return result

    def summary(self) -> dict[str, Any]:
        """Return post-trade analytics summary."""
        if not self._trades:
            return {
                "pnl": {"total_pnl": 0.0, "avg_pnl_per_trade": 0.0, "trades": 0},
                "trades": 0,
                "win_rate": 0.0,
                "avg_pnl": 0.0,
                "max_drawdown": 0.0,
                "expectancy": 0.0,
                "profit_factor": 0.0,
                "edge_captured": 0.0,
                "strategy_breakdown": {},
                "regime_breakdown": {},
                "execution_quality_metrics": {
                    "avg_slippage_impact": 0.0,
                    "avg_timing_effectiveness": 0.0,
                    "avg_exit_efficiency": 0.0,
                },
                "risk_metrics": self._compute_risk_metrics(),
            }
        total_trades = len(self._trades)
        total_pnl = sum(t.pnl for t in self._trades)
        wins = [t for t in self._trades if t.pnl > 0]
        losses = [t for t in self._trades if t.pnl < 0]
        win_rate = len(wins) / total_trades
        avg_win = sum(t.pnl for t in wins) / len(wins) if wins else 0.0
        avg_loss_abs = abs(sum(t.pnl for t in losses) / len(losses)) if losses else 0.0
        gross_profit = sum(t.pnl for t in wins)
        gross_loss_abs = abs(sum(t.pnl for t in losses))
        profit_factor = gross_profit / gross_loss_abs if gross_loss_abs > 0 else (float("inf") if gross_profit > 0 else 0.0)
        expectancy = (win_rate * avg_win) - ((1.0 - win_rate) * avg_loss_abs)
        edge_samples = [t.actual_return / t.theoretical_edge for t in self._trades if t.theoretical_edge > 1e-9]
        execution_quality_metrics = {
            "avg_slippage_impact": round(sum(t.slippage_impact for t in self._trades) / total_trades, 6),
            "avg_timing_effectiveness": round(sum(t.timing_effectiveness for t in self._trades) / total_trades, 6),
            "avg_exit_efficiency": round(sum(t.exit_efficiency for t in self._trades) / total_trades, 6),
        }
        return {
            "pnl": {
                "total_pnl": round(total_pnl, 6),
                "avg_pnl_per_trade": round(total_pnl / total_trades, 6),
                "trades": total_trades,
            },
            "trades": total_trades,
            "win_rate": round(win_rate, 6),
            "avg_pnl": round(total_pnl / total_trades, 6),
            "max_drawdown": self._compute_risk_metrics()["max_drawdown"],
            "expectancy": round(expectancy, 6),
            "profit_factor": round(profit_factor, 6) if profit_factor != float("inf") else float("inf"),
            "edge_captured": round(sum(edge_samples) / len(edge_samples), 6) if edge_samples else 0.0,
            "strategy_breakdown": self._build_group_breakdown("strategy_source"),
            "regime_breakdown": self._build_group_breakdown("regime_at_entry"),
            "execution_quality_metrics": execution_quality_metrics,
            "risk_metrics": self._compute_risk_metrics(),
        }

    def optimization_output(self) -> dict[str, Any]:
        """Convert analytics summary into bounded optimization signals."""
        summary = self.summary()
        strategy_keys = ("S1", "S2", "S3", "S5")
        neutral_output = {
            "strategy_weights": {key: 1.0 for key in strategy_keys},
            "regime_weights": {"NEWS": 1.0, "ARBITRAGE": 1.0, "SMART_MONEY": 1.0, "CHAOTIC": 1.0},
            "execution_adjustments": {
                "p10_max_spread_multiplier": 1.0,
                "p10_slippage_guard_multiplier": 1.0,
                "p12_wait_cycle_bias": 0,
                "p12_reevaluation_window_multiplier": 1.0,
                "p13_exit_sensitivity_multiplier": 1.0,
            },
            "risk_adjustments": {
                "aggression_multiplier": 1.0,
                "size_multiplier": 1.0,
            },
            "fallback_to_neutral": False,
        }
        trades = int(summary.get("trades", 0))
        if trades < 3:
            neutral_output["fallback_to_neutral"] = True
            return neutral_output

        strategy_breakdown = summary.get("strategy_breakdown", {})
        risk_metrics = summary.get("risk_metrics", {})
        expectancy = float(summary.get("expectancy", 0.0))
        strategy_weights: dict[str, float] = {key: 1.0 for key in strategy_keys}

        scores: dict[str, float] = {}
        max_abs_pnl = max(
            (abs(float(row.get("pnl", 0.0))) for row in strategy_breakdown.values()),
            default=1.0,
        )
        expectancy_norm = self._clamp(expectancy / 20.0, -1.0, 1.0)
        global_drawdown = self._clamp(float(risk_metrics.get("max_drawdown", 0.0)), 0.0, 1.0)
        drawdown_component = 1.0 - global_drawdown
        for strategy_name in strategy_keys:
            row = strategy_breakdown.get(strategy_name, {})
            if not row:
                continue
            pnl = float(row.get("pnl", 0.0))
            win_rate = self._clamp(float(row.get("win_rate", 0.0)), 0.0, 1.0)
            avg_return = self._clamp(float(row.get("avg_return", 0.0)) / 0.10, -1.0, 1.0)
            pnl_component = self._clamp((pnl / max(max_abs_pnl, 1e-6)), -1.0, 1.0)
            score = (
                (0.30 * ((pnl_component + 1.0) / 2.0))
                + (0.30 * win_rate)
                + (0.20 * ((avg_return + 1.0) / 2.0))
                + (0.10 * ((expectancy_norm + 1.0) / 2.0))
                + (0.10 * drawdown_component)
            )
            scores[strategy_name] = self._clamp(score, 0.0, 1.0)

        if scores:
            low = min(scores.values())
            high = max(scores.values())
            span = max(high - low, 1e-6)
            for strategy_name, score in scores.items():
                normalized = (score - low) / span if high > low else 0.5
                if normalized >= 0.75:
                    modifier = 1.08
                elif normalized <= 0.15:
                    modifier = 0.75
                elif normalized <= 0.35:
                    modifier = 0.90
                else:
                    modifier = 0.95 + (normalized - 0.35) * 0.20
                strategy_weights[strategy_name] = round(self._clamp(modifier, 0.75, 1.15), 6)

        regime_breakdown = summary.get("regime_breakdown", {})
        regime_weights = {"NEWS": 1.0, "ARBITRAGE": 1.0, "SMART_MONEY": 1.0, "CHAOTIC": 1.0}
        regime_scores: dict[str, float] = {}
        max_abs_regime_pnl = max(
            (abs(float(row.get("pnl", 0.0))) for row in regime_breakdown.values()),
            default=1.0,
        )
        for regime_name, row in regime_breakdown.items():
            pnl = float(row.get("pnl", 0.0))
            win_rate = self._clamp(float(row.get("win_rate", 0.0)), 0.0, 1.0)
            avg_return = self._clamp(float(row.get("avg_return", 0.0)) / 0.10, -1.0, 1.0)
            pnl_component = self._clamp((pnl / max(max_abs_regime_pnl, 1e-6)), -1.0, 1.0)
            regime_scores[regime_name] = self._clamp(
                (0.45 * ((pnl_component + 1.0) / 2.0))
                + (0.35 * win_rate)
                + (0.20 * ((avg_return + 1.0) / 2.0)),
                0.0,
                1.0,
            )
        if regime_scores:
            low = min(regime_scores.values())
            high = max(regime_scores.values())
            span = max(high - low, 1e-6)
            for regime_name, score in regime_scores.items():
                normalized = (score - low) / span if high > low else 0.5
                regime_weights[regime_name] = round(self._clamp(0.85 + (normalized * 0.30), 0.85, 1.15), 6)

        execution_metrics = summary.get("execution_quality_metrics", {})
        avg_slippage_impact = self._clamp(float(execution_metrics.get("avg_slippage_impact", 0.0)), 0.0, 1.0)
        avg_timing_effectiveness = self._clamp(float(execution_metrics.get("avg_timing_effectiveness", 0.0)), 0.0, 1.0)
        avg_exit_efficiency = self._clamp(float(execution_metrics.get("avg_exit_efficiency", 0.0)), 0.0, 1.0)
        p10_tighten = self._clamp((avg_slippage_impact - 0.02) / 0.06, 0.0, 1.0)
        p12_timing_penalty = self._clamp((0.60 - avg_timing_effectiveness) / 0.40, 0.0, 1.0)
        p13_exit_penalty = self._clamp((0.60 - avg_exit_efficiency) / 0.40, 0.0, 1.0)
        execution_adjustments = {
            "p10_max_spread_multiplier": round(self._clamp(1.0 - (0.15 * p10_tighten), 0.85, 1.0), 6),
            "p10_slippage_guard_multiplier": round(self._clamp(1.0 - (0.20 * p10_tighten), 0.80, 1.0), 6),
            "p12_wait_cycle_bias": int(round(self._clamp(p12_timing_penalty * 2.0, 0.0, 2.0))),
            "p12_reevaluation_window_multiplier": round(self._clamp(1.0 + (0.20 * p12_timing_penalty), 1.0, 1.2), 6),
            "p13_exit_sensitivity_multiplier": round(self._clamp(1.0 - (0.20 * p13_exit_penalty), 0.80, 1.0), 6),
        }

        loss_streak = int(risk_metrics.get("loss_streak", 0))
        max_drawdown = self._clamp(float(risk_metrics.get("max_drawdown", 0.0)), 0.0, 1.0)
        avg_drawdown = self._clamp(float(risk_metrics.get("avg_drawdown", 0.0)), 0.0, 1.0)
        drawdown_pressure = self._clamp((max_drawdown - 0.04) / 0.20, 0.0, 1.0)
        avg_drawdown_pressure = self._clamp((avg_drawdown - 0.02) / 0.10, 0.0, 1.0)
        streak_pressure = self._clamp((loss_streak - 1) / 4.0, 0.0, 1.0)
        risk_adjustments = {
            "aggression_multiplier": round(
                self._clamp(1.0 - (0.15 * max(drawdown_pressure, avg_drawdown_pressure)), 0.85, 1.0),
                6,
            ),
            "size_multiplier": round(self._clamp(1.0 - (0.15 * streak_pressure), 0.85, 1.0), 6),
        }

        return {
            "strategy_weights": strategy_weights,
            "regime_weights": regime_weights,
            "execution_adjustments": execution_adjustments,
            "risk_adjustments": risk_adjustments,
            "fallback_to_neutral": False,
        }

    @staticmethod
    def _clamp(value: float, lower: float, upper: float) -> float:
        return min(max(value, lower), upper)

    def _calculate_sharpe(self) -> float:
        """Placeholder for Sharpe ratio."""
        return 0.0

    def reconcile(self, trace_engine: "TradeTraceEngine") -> bool:
        """Verify analytics match trace data."""
        trace_pnl = sum(t.pnl for t in trace_engine.get_traces())
        analytics_pnl = sum(t.pnl for t in self._trades)
        if abs(trace_pnl - analytics_pnl) > 1e-6:
            raise ValueError(f"Reconciliation failed: trace_pnl={trace_pnl}, analytics_pnl={analytics_pnl}")
        return True
