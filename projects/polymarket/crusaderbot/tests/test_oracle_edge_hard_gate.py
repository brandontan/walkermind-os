"""Oracle edge + distance HARD entry gate (WARP/oracle-edge-entry-gate).

late_entry_v3 already computes, per candle, the advisory verdict
``oracle_edge_would_pass`` = (min_dist <= |delta| <= max_dist) AND
(max(edge_up, edge_down) >= min_edge), using the Kreo-aligned per-preset bands in
``signal_scan_job._CANDLE_PRESET_EDGE``. Before this lane the verdict was logged
but NEVER enforced, so a candle that met only the structural gates (time window,
ask_diff, spread, price band) still entered even with no edge / no conviction —
effectively time-gated. This lane promotes the verdict to a hard reject so entry
fires ONLY when the edge + distance rules are met.

Enforcement is gated by ``OracleEdgeConfig.hard_reject`` (set from
``ORACLE_EDGE_HARD_REJECT_ENABLED``, default True) and is FAIL-OPEN: it only acts
when the oracle produced a 'computed' verdict, so a dark feed
(ORACLE_ENABLED=false), warmup, feed_down, or stale tick never blocks a trade.

Gate predicate: ``late_entry_v3._oracle_edge_hard_rejects``.
Wired in: ``late_entry_v3._evaluate_market`` (returns reason
``oracle_edge_distance_reject``). Config flag built into the edge_cfg in
``signal_scan_job._build_oracle_edge_cfg``.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from projects.polymarket.crusaderbot import config as crusaderbot_config
from projects.polymarket.crusaderbot.domain.strategy.strategies.late_entry_v3 import (
    OracleEdgeConfig,
    _oracle_edge_hard_rejects,
)


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("OPERATOR_CHAT_ID", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("WALLET_HD_SEED", "seed")
    monkeypatch.setenv("WALLET_ENCRYPTION_KEY", "k")
    monkeypatch.setenv("POLYGON_RPC_URL", "https://rpc")
    monkeypatch.setenv("ALCHEMY_POLYGON_WS_URL", "wss://ws")


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    crusaderbot_config.get_settings.cache_clear()
    yield
    crusaderbot_config.get_settings.cache_clear()


def _cfg(hard_reject: bool) -> OracleEdgeConfig:
    return OracleEdgeConfig(enabled=True, hard_reject=hard_reject)


def _computed(would_pass: bool) -> dict:
    return {
        "oracle_edge_status": "computed",
        "oracle_edge_would_pass": would_pass,
        "oracle_distance": 0.001,
        "oracle_edge_up": 0.03,
        "oracle_edge_down": -0.01,
    }


# ---------------------------------------------------------------------
# OracleEdgeConfig default — existing construction sites stay observe-only.
# ---------------------------------------------------------------------


def test_hard_reject_defaults_false():
    """Back-compat: every existing OracleEdgeConfig construction site (tests,
    advisory-only callers) defaults to observe-only — only the scan orchestrator
    opts in via the config flag."""
    assert OracleEdgeConfig().hard_reject is False
    assert OracleEdgeConfig(enabled=True).hard_reject is False


# ---------------------------------------------------------------------
# Gate predicate — the single source of the enforcement decision.
# ---------------------------------------------------------------------


def test_rejects_when_computed_and_would_not_pass():
    """The core case: hard_reject ON + oracle computed a verdict + would_pass
    False → SKIP. This is what stops a no-edge / out-of-band candle entering."""
    assert _oracle_edge_hard_rejects(_cfg(True), _computed(False)) is True


def test_allows_when_computed_and_would_pass():
    """A candle that meets the edge + distance rules (would_pass True) is NOT
    rejected by this gate."""
    assert _oracle_edge_hard_rejects(_cfg(True), _computed(True)) is False


def test_no_op_when_hard_reject_disabled():
    """Observe-only mode (ORACLE_EDGE_HARD_REJECT_ENABLED=false): even a clear
    would_pass=False verdict does not block."""
    assert _oracle_edge_hard_rejects(_cfg(False), _computed(False)) is False


def test_fail_open_when_cfg_none():
    """No edge_cfg (oracle wiring off entirely) → never blocks."""
    assert _oracle_edge_hard_rejects(None, _computed(False)) is False


@pytest.mark.parametrize(
    "status",
    ["warming_up", "feed_down", "stale", "error", "disabled"],
)
def test_fail_open_on_non_computed_status(status: str):
    """FAIL-OPEN: a dark / warming / dropped / stale / errored feed must never
    halt trading — only a 'computed' verdict can reject. The structural gates
    remain the floor in every degraded-oracle state."""
    meta = {"oracle_edge_status": status, "oracle_edge_would_pass": False}
    assert _oracle_edge_hard_rejects(_cfg(True), meta) is False


def test_fail_open_when_status_absent():
    """Empty metadata (advisory not computed) → never blocks."""
    assert _oracle_edge_hard_rejects(_cfg(True), {}) is False


def test_would_pass_missing_does_not_reject():
    """A 'computed' verdict that somehow omits would_pass must not reject (only an
    explicit False blocks — guards against a partial metadata stamp)."""
    meta = {"oracle_edge_status": "computed"}
    assert _oracle_edge_hard_rejects(_cfg(True), meta) is False


def test_would_pass_none_does_not_reject():
    """would_pass explicitly None (not False) → not a reject."""
    meta = {"oracle_edge_status": "computed", "oracle_edge_would_pass": None}
    assert _oracle_edge_hard_rejects(_cfg(True), meta) is False


# ---------------------------------------------------------------------
# Config knob — default ON + env override.
# ---------------------------------------------------------------------


def test_config_default_on(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.delenv("ORACLE_EDGE_HARD_REJECT_ENABLED", raising=False)
    s = crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert s.ORACLE_EDGE_HARD_REJECT_ENABLED is True


def test_config_env_override_false(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("ORACLE_EDGE_HARD_REJECT_ENABLED", "false")
    s = crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert s.ORACLE_EDGE_HARD_REJECT_ENABLED is False


def test_config_env_override_true(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("ORACLE_EDGE_HARD_REJECT_ENABLED", "true")
    s = crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert s.ORACLE_EDGE_HARD_REJECT_ENABLED is True
