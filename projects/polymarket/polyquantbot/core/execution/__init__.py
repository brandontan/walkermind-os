"""core/execution — trade executor with risk validation, dedup, and paper/live support."""
from .executor import ExecutionResult, TradeExecutor, execute_trade

__all__ = ["execute_trade", "ExecutionResult", "TradeExecutor"]
