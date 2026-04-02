"""core.pipeline — Trading pipeline runners and loop orchestration."""
from __future__ import annotations

from .trading_loop import run_trading_loop

__all__ = ["run_trading_loop"]
