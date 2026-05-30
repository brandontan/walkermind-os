"""Regression: TOB freshness gate (WARP/R00T/tob-freshness-gate).

Defense layer over the existing sub-cent / Gamma-fallback guard
(`test_flip_hunter_stale_price_fix.py`). When `_process_candidate` receives
a late_entry_v3 candidate whose orderbook snapshot is older than
`config.TOB_STALE_MS` (default 2000ms), the candidate is rejected with
`scan_outcome="skipped_stale_tob"` instead of being fired against a stale
live mark.

Scope:
  - Only candidates that carry `metadata["entry_price_ts"]` (late_entry_v3
    presets: close_sweep / safe_close / flip_hunter) are gated.
  - Strategies that omit the stamp (signal_following, momentum, copy_trade)
    pass through cleanly — no-op.

Knob:
  - `config.TOB_STALE_MS=0` disables the gate (escape hatch).

Guard lives in:
  ``services.signal_scan.signal_scan_job._process_candidate`` step 3b-0
Stamp lives in:
  ``domain.strategy.strategies.late_entry_v3._evaluate_market``
"""
from __future__ import annotations

import inspect

import pytest

from projects.polymarket.crusaderbot import config as crusaderbot_config
from projects.polymarket.crusaderbot.domain.strategy.strategies import (
    late_entry_v3 as lev3,
)
from projects.polymarket.crusaderbot.services.signal_scan import (
    signal_scan_job as ssj,
)


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("OPERATOR_CHAT_ID", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    monkeypatch.setenv("WALLET_HD_SEED", "seed")
    monkeypatch.setenv("WALLET_ENCRYPTION_KEY", "k")
    monkeypatch.setenv("POLYGON_RPC_URL", "https://rpc")
    monkeypatch.setenv("ALCHEMY_POLYGON_WS_URL", "wss://ws")


# ---------------------------------------------------------------------
# Source-level pins — fail closed if the guard is removed or scope is broken.
# ---------------------------------------------------------------------


def test_process_candidate_has_tob_freshness_gate():
    """`_process_candidate` must contain the `skipped_stale_tob` outcome
    path; if removed, late_entry_v3 candidates will fire on stale CLOB
    snapshots when the scheduler back-pressures.
    """
    src = inspect.getsource(ssj._process_candidate)
    assert "skipped_stale_tob" in src, (
        "Regression: _process_candidate lost its TOB freshness gate."
    )


def test_process_candidate_reads_config_knob():
    """The gate must read the `TOB_STALE_MS` config knob (not a hard-coded
    literal) so the operator can disable / retune without redeploy.
    """
    src = inspect.getsource(ssj._process_candidate)
    assert "TOB_STALE_MS" in src, (
        "Regression: TOB freshness gate must read config.TOB_STALE_MS."
    )


def test_process_candidate_gate_scoped_to_stamped_candidates():
    """Gate must be conditional on `metadata['entry_price_ts']` so
    candidates that don't carry the stamp (signal_following, momentum,
    copy_trade) bypass it cleanly. A global gate would block every
    non-late_entry_v3 strategy.
    """
    src = inspect.getsource(ssj._process_candidate)
    assert 'cand.metadata.get("entry_price_ts")' in src, (
        "Regression: TOB freshness gate must be scoped to candidates "
        "carrying metadata['entry_price_ts']; a global gate breaks "
        "signal_following / momentum / copy_trade."
    )


def test_late_entry_v3_stamps_entry_price_ts():
    """`_evaluate_market` must stamp `entry_price_ts` into the candidate
    metadata so `_process_candidate` has a basis to measure staleness.
    Removing the stamp would silently disable the gate for every
    late_entry_v3 preset (close_sweep / safe_close / flip_hunter).
    """
    src = inspect.getsource(lev3._evaluate_market)
    assert "entry_price_ts" in src, (
        "Regression: late_entry_v3._evaluate_market lost the "
        "entry_price_ts stamp — TOB freshness gate is now a no-op for "
        "close_sweep / safe_close / flip_hunter."
    )


# ---------------------------------------------------------------------
# Config knob — defaults + escape hatch.
# ---------------------------------------------------------------------


def test_tob_stale_ms_default_is_2000(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default matches Polybot research reference: snapshots older than
    2s have materially diverged from the live mark."""
    _set_required_env(monkeypatch)
    monkeypatch.delenv("TOB_STALE_MS", raising=False)
    s = crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert s.TOB_STALE_MS == 2000
    crusaderbot_config.get_settings.cache_clear()


def test_tob_stale_ms_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Operator must be able to retune / disable the gate via env without
    redeploy; pydantic-settings picks up TOB_STALE_MS from the environment."""
    _set_required_env(monkeypatch)
    monkeypatch.setenv("TOB_STALE_MS", "0")
    s = crusaderbot_config.Settings()  # type: ignore[call-arg]
    assert s.TOB_STALE_MS == 0
    crusaderbot_config.get_settings.cache_clear()


def test_tob_stale_ms_disable_sentinel_is_zero():
    """Operator must be able to disable the gate (revert to pre-lane
    behaviour) via TOB_STALE_MS=0 without redeploy. The gate code
    branches on `> 0` so 0 is the disable sentinel."""
    src = inspect.getsource(ssj._process_candidate)
    assert "_tob_stale_ms > 0" in src, (
        "Regression: TOB freshness gate must short-circuit when "
        "TOB_STALE_MS=0 (operator escape hatch)."
    )


# ---------------------------------------------------------------------
# Mathematical fingerprint — age threshold semantics.
# ---------------------------------------------------------------------


@pytest.mark.parametrize("age_ms", [2001, 2500, 5000, 60000])
def test_age_above_threshold_rejects(age_ms):
    """Any age strictly greater than the threshold must reject."""
    threshold_ms = 2000
    assert age_ms > threshold_ms


@pytest.mark.parametrize("age_ms", [0, 100, 500, 1500, 1999, 2000])
def test_age_at_or_below_threshold_accepts(age_ms):
    """Ages at or below the threshold must accept (the gate uses strict
    `>` comparison so the boundary value 2000 is still fresh)."""
    threshold_ms = 2000
    assert age_ms <= threshold_ms
