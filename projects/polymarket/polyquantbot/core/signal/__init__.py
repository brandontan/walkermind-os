"""core.signal — Edge-based signal generation for PolyQuantBot.

Exports:
    generate_signals  — async function that evaluates a list of markets and
                        returns signals that pass the edge + liquidity filter.
    SignalResult      — dataclass describing a generated signal.
"""
from __future__ import annotations

from .signal_engine import SignalResult, generate_signals

__all__ = ["generate_signals", "SignalResult"]
