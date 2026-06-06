"""Hermetic coverage for the WARP-78 cutover pipeline dry-run harness.

Runs the synthetic, in-memory dry-run end-to-end and asserts every
pipeline-correctness check passes. No DB, no network, no prod writes.
"""
from __future__ import annotations

from projects.polymarket.crusaderbot.scripts.cutover_pipeline_dryrun import (
    GroundTruth,
    derive_ev_model,
    generate_synthetic_rows,
    run_dryrun,
    validate_weight_recovery,
)


def test_dryrun_all_checks_pass() -> None:
    checks, artifacts = run_dryrun(rows_per_cell=200, seed=78)
    failed = [c.name for c in checks if not c.passed and not c.informational]
    assert not failed, f"dry-run correctness checks failed: {failed}"
    assert artifacts["rows"] == 800
    assert set(artifacts["cells"]) == {"BTC/5m", "BTC/15m", "ETH/5m", "ETH/15m"}


def test_dryrun_correctness_stable_across_seeds() -> None:
    # Pipeline CORRECTNESS (no NaN / weight recovery / serialization / consistency)
    # must hold under any draw. Informational statistical-power checks may vary.
    for seed in (1, 7, 99):
        checks, _ = run_dryrun(rows_per_cell=200, seed=seed)
        failed = [c.name for c in checks if not c.passed and not c.informational]
        assert not failed, f"seed={seed} correctness failed: {failed}"


def test_ground_truth_momentum_sign_recovered() -> None:
    rows = generate_synthetic_rows(rows_per_cell=200, seed=78)
    model = derive_ev_model(rows)
    gt = GroundTruth()
    for ck, cell in (model["cells"]).items():
        rules = cell["rules"]
        assert rules["close_sweep"]["weights"]["momentum"] > 0.0, ck
        assert rules["flip_hunter"]["weights"]["momentum"] < 0.0, ck
        # dead per-asset constant contributes nothing
        assert rules["close_sweep"]["weights"][gt.dead_factor] == 0.0, ck


def test_weight_recovery_checks_isolated() -> None:
    rows = generate_synthetic_rows(rows_per_cell=200, seed=78)
    model = derive_ev_model(rows)
    checks = validate_weight_recovery(model, GroundTruth())
    assert all(c.passed for c in checks), [c.name for c in checks if not c.passed]
