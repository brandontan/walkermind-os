"""Track A trade engine — canonical paper execution entry point.

Exposes:
    TradeSignal  — typed signal input contract
    TradeResult  — typed execution outcome
    TradeEngine  — signal → risk gate → paper order → paper position
"""
from .engine import TradeEngine, TradeResult, TradeSignal

__all__ = ["TradeEngine", "TradeSignal", "TradeResult"]
