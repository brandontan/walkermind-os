from __future__ import annotations

from execution.drift_guard import evaluate_execution_price_drift
from execution.engine import ExecutionEngine


def test_p17_4_drift_guard_allows_price_within_threshold() -> None:
    result = evaluate_execution_price_drift(
        expected_price=0.50,
        execution_price=0.505,
        max_drift_ratio=0.02,
    )
    assert result.allowed is True
    assert result.drift_ratio > 0.0


def test_p17_4_drift_guard_rejects_price_over_threshold() -> None:
    result = evaluate_execution_price_drift(
        expected_price=0.50,
        execution_price=0.55,
        max_drift_ratio=0.02,
    )
    assert result.allowed is False
    assert result.drift_ratio > result.max_drift_ratio


def test_p17_4_import_alignment_engine_and_drift_guard_from_active_root() -> None:
    engine = ExecutionEngine(starting_equity=10_000.0)
    assert engine is not None
