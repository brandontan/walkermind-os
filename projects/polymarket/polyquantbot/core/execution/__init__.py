"""core.execution — Trade execution engine for PolyQuantBot.

Exports:
    execute_trade   — async function that validates and executes a single signal.
    TradeResult     — dataclass describing the outcome of an execution attempt.
"""
from __future__ import annotations

from .executor import TradeResult, execute_trade

__all__ = ["execute_trade", "TradeResult"]
