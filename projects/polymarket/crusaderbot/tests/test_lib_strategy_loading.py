"""Regression: every lib strategy must actually load via the runner.

Guards the F-HIGH-2 root cause — lib/ strategies silently failed to load in
prod because (a) lib/ lived at the repo root, outside the Docker build context,
and (b) the file-path loader could not resolve the strategies' package-relative
imports (``from ..strategy_base import ...``). Both produced zero auto-trade
candidates with no error surfaced.

These tests deliberately do NOT mock run_lib_strategy / _load_strategy — the
rest of the suite mocks them, which is exactly why the breakage went unnoticed
at 1600+ passing tests. If lib/ ever stops shipping as an importable subpackage,
or a strategy's imports break, these tests fail loudly.
"""
from __future__ import annotations

import pytest

from projects.polymarket.crusaderbot.services.signal_scan.lib_strategy_runner import (
    DEFERRED_STRATEGIES,
    ENABLED_STRATEGIES,
    _load_strategy,
)
from projects.polymarket.crusaderbot.lib.strategies import get_strategy


@pytest.mark.parametrize("name", list(ENABLED_STRATEGIES) + list(DEFERRED_STRATEGIES))
def test_lib_strategy_loads(name: str) -> None:
    """Each catalogued lib strategy loads and reports its own name."""
    strategy = _load_strategy(name)
    assert strategy is not None
    assert getattr(strategy, "name", None) == name


@pytest.mark.parametrize("name", list(ENABLED_STRATEGIES))
def test_get_strategy_returns_named_instance(name: str) -> None:
    """ensemble's get_strategy() resolves each enabled strategy by name."""
    strategy = get_strategy(name)
    assert getattr(strategy, "name", None) == name


def test_get_strategy_unknown_raises_value_error() -> None:
    """Unknown names raise ValueError so ensemble degrades gracefully."""
    with pytest.raises(ValueError):
        get_strategy("does_not_exist_strategy")


def test_ensemble_builds_sub_strategies() -> None:
    """ensemble loads and instantiates its sub-strategies without raising."""
    ensemble = _load_strategy("ensemble")
    ensemble.initialize({"strategies": "momentum,value_investor,trend_breakout"})
    assert len(ensemble.sub_strategies) == 3
