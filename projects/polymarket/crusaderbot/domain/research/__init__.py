"""Research / validation plane — Phase-2c.

Out-of-sample validation infrastructure that gates LIVE capital, addressing the
WARP-51 alpha audit F-1 (no backtest/validation framework exists). Pure analytics
over already-persisted trading history — no execution, no risk authority, no new
external calls.

* ``monte_carlo`` — dependency-free bootstrap simulator: resamples a module's
  realized per-trade return distribution to estimate risk-of-ruin, drawdown-depth,
  and losing-streak tails at a risk profile's sizing.
* ``robustness`` — classifies each strategy module ROBUST / FRAGILE / UNTRADEABLE
  / INSUFFICIENT_DATA from the Monte Carlo result, and exposes the LIVE-eligibility
  gate the activation layer can consult.

See ``docs/blueprint/playbook.md`` §12.2.
"""
from __future__ import annotations

from .monte_carlo import MCResult, simulate
from .robustness import (
    Classification,
    ModuleRobustness,
    classify,
    classify_modules,
    live_eligible,
)

__all__ = [
    "MCResult",
    "simulate",
    "Classification",
    "ModuleRobustness",
    "classify",
    "classify_modules",
    "live_eligible",
]
