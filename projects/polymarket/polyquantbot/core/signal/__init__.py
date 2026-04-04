"""core.signal — Edge-based signal generation for PolyQuantBot.

Exports:
    generate_signals            — async function that evaluates a list of markets and
                                  returns signals that pass the edge + liquidity filter.
    generate_synthetic_signals  — async function for force-trade fallback injection.
    SignalResult                — dataclass describing a generated signal.
"""
from __future__ import annotations

from .signal_engine import SignalResult, generate_signals, generate_synthetic_signals

__all__ = ["generate_signals", "generate_synthetic_signals", "SignalResult"]
