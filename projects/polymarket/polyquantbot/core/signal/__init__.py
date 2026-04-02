"""core/signal — edge-based signal generation with EV and Kelly sizing."""
from .signal_engine import SignalResult, generate_signals

__all__ = ["generate_signals", "SignalResult"]
