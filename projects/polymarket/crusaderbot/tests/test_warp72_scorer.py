"""WARP-72 Phase 2 — SMART STRIKE scoring orchestrator tests.

Covers the scorer (side/win helpers, neutral fallback = precedence ladder, the
trained linear score, the additive Oracle deny-gate), the offline trainer
(per-cell weight derivation, SOL skip, file round-trip), the scorer-vs-router A/B
harness, and the signal_scan_job shadow wiring. Hermetic — no DB, no network.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from projects.polymarket.crusaderbot.domain.strategy import scorer as sc
from projects.polymarket.crusaderbot.domain.strategy import scorer_ab as ab
from projects.polymarket.crusaderbot.domain.strategy import scorer_trainer as tr
from projects.polymarket.crusaderbot.domain.strategy.scorer import (
    ORACLE_DENY_THRESHOLDS,
    StrategyScorer,
)


def _run(coro):
    return asyncio.run(coro)


# ── synthetic dataset ─────────────────────────────────────────────────────
# momentum is constructed to perfectly predict the realized direction: high
# momentum → UP, low momentum → DOWN. All other factors are held constant so
# their derived weight is 0 (zero variance) and only momentum discriminates.
def _row(asset, momentum, outcome, *, fav_side="YES", router_rule="flip_hunter",
         oracle_edge=0.05, oracle_status="computed", timeframe="5m"):
    return {
        "condition_id": f"0x{asset}{momentum}{outcome}",
        "asset": asset,
        "timeframe": timeframe,
        "fav_side": fav_side,
        "entry_side": fav_side,
        "realized_outcome": outcome,
        "realized_delta": 0.001 if outcome == "UP" else -0.001,
        "momentum": momentum,
        "volatility_sigma": 0.0001,
        "liquidity_usdc": 1000.0,
        "spread": 0.02,
        "orderbook_depth_usdc": 1000.0,
        "ttl_sec": 20.0,
        "oracle_edge": oracle_edge,
        "oracle_edge_status": oracle_status,
        "router_selected_rule": router_rule,
        "evaluated_rule": router_rule,
    }


def _dataset(asset="btc", n_each=10):
    rows = []
    for i in range(n_each):
        rows.append(_row(asset, 0.0020 + i * 0.0001, "UP"))      # high momentum → UP
        rows.append(_row(asset, -0.0020 - i * 0.0001, "DOWN"))   # low momentum → DOWN
    return rows


# ── side / win helpers ────────────────────────────────────────────────────
def test_rule_entry_side_favorite_vs_underdog():
    assert sc.rule_entry_side("close_sweep", "YES") == "YES"
    assert sc.rule_entry_side("safe_close", "NO") == "NO"
    # flip_hunter is the underdog (opposite of favored).
    assert sc.rule_entry_side("flip_hunter", "YES") == "NO"
    assert sc.rule_entry_side("flip_hunter", "NO") == "YES"
    assert sc.rule_entry_side("close_sweep", None) is None


def test_winning_side_and_rule_won():
    assert sc.winning_side("UP") == "YES"
    assert sc.winning_side("DOWN") == "NO"
    assert sc.winning_side("FLAT") is None
    # favorite on YES wins when UP; underdog on YES-fav (enters NO) wins when DOWN.
    assert sc.rule_won("close_sweep", "YES", "UP") is True
    assert sc.rule_won("close_sweep", "YES", "DOWN") is False
    assert sc.rule_won("flip_hunter", "YES", "DOWN") is True
    assert sc.rule_won("flip_hunter", "YES", "UP") is False
    assert sc.rule_won("close_sweep", None, "UP") is None  # undecidable


# ── neutral scorer = precedence ladder ────────────────────────────────────
def test_neutral_scorer_reproduces_precedence():
    s = StrategyScorer.neutral()
    assert s.score_rule("BTC/5m", "close_sweep", {}) == 0.0
    ranked = s.rank("BTC/5m", {}, ["flip_hunter", "safe_close", "close_sweep"])
    # All scores 0, none denied → ordered by precedence.
    assert [r.rule for r in ranked] == ["close_sweep", "safe_close", "flip_hunter"]
    assert s.select("BTC/5m", {}, ["flip_hunter", "safe_close"]) == "safe_close"


def test_from_file_missing_is_neutral(tmp_path):
    s = StrategyScorer.from_file(tmp_path / "nope.json")
    assert s.trained is False
    assert s.select(None, {}, ["close_sweep", "flip_hunter"]) == "close_sweep"


# ── Oracle deny-gate (additive) ───────────────────────────────────────────
def test_oracle_deny_only_when_computed_and_below_threshold():
    # close_sweep threshold = 0.02. Below + computed → denied.
    assert StrategyScorer.oracle_denied("close_sweep", 0.01, "computed") is True
    # At/above threshold → not denied.
    assert StrategyScorer.oracle_denied("close_sweep", 0.02, "computed") is False
    # Non-computed status is fail-open (never deny).
    assert StrategyScorer.oracle_denied("close_sweep", 0.0, "warming_up") is False
    assert StrategyScorer.oracle_denied("close_sweep", None, "computed") is False
    # Each preset has its own threshold (WARP-66).
    assert ORACLE_DENY_THRESHOLDS == {
        "close_sweep": 0.020, "safe_close": 0.010, "flip_hunter": 0.030,
    }


def test_oracle_deny_cannot_be_overridden_by_score():
    # Build a model where close_sweep scores far higher than flip_hunter, but
    # close_sweep's Oracle edge is below its threshold → it must still be denied.
    model = tr.build_weights(_dataset("btc"))
    s = StrategyScorer.from_model(model)
    # edge 0.015: below close_sweep (0.02) and safe_close? no, safe_close=0.01 ok;
    # below flip_hunter (0.03). So close_sweep + flip_hunter denied, safe_close ok.
    pick = s.select(
        "BTC/5m", {"momentum": 0.003}, ["close_sweep", "safe_close", "flip_hunter"],
        oracle_edge=0.015, oracle_edge_status="computed",
    )
    assert pick == "safe_close"  # only non-denied rule survives, regardless of score


# ── trainer ───────────────────────────────────────────────────────────────
def test_build_weights_derives_target_cells_and_skips_sol():
    rows = _dataset("btc") + _dataset("eth")
    model = tr.build_weights(rows)
    assert model["trained"] is True
    assert set(model["cells"]) == {"BTC/5m", "ETH/5m"}
    # SOL/5m has no rows → explicitly skipped with reason no_data.
    assert model["skipped"]["SOL/5m"] == "no_data"
    assert model["train_filter"] == {"outcome_source": "open_to_close", "settled": True}


def test_derived_weight_signs_match_construction():
    model = tr.build_weights(_dataset("btc"))
    cell = model["cells"]["BTC/5m"]
    cs = cell["rules"]["close_sweep"]["weights"]["momentum"]
    fh = cell["rules"]["flip_hunter"]["weights"]["momentum"]
    # close_sweep (favorite/YES) wins on UP, which tracks high momentum → +weight.
    assert cs > 0.0
    # flip_hunter (underdog) wins on DOWN → negatively correlated with momentum.
    assert fh < 0.0
    # constant factors have zero variance → zero weight.
    assert cell["rules"]["close_sweep"]["weights"]["spread"] == 0.0
    # base win-rate ~0.5 (half UP, half DOWN, fav YES).
    assert abs(cell["rules"]["close_sweep"]["base_winrate"] - 0.5) < 1e-9


def test_trained_scorer_discriminates_on_momentum():
    s = StrategyScorer.from_model(tr.build_weights(_dataset("btc")))
    rules = ["close_sweep", "safe_close", "flip_hunter"]
    # High momentum → close_sweep (favorite) should outrank flip_hunter.
    assert s.select("BTC/5m", {"momentum": 0.003}, rules) == "close_sweep"
    # Low momentum → flip_hunter (underdog) should win.
    assert s.select("BTC/5m", {"momentum": -0.003}, rules) == "flip_hunter"


def test_write_weights_roundtrip(tmp_path):
    out = tmp_path / "config" / "scorer_weights.json"
    model = tr.build_weights(_dataset("btc"))
    path = tr.write_weights(model, out)
    assert path.exists()
    loaded = json.loads(path.read_text())
    assert loaded["cells"]["BTC/5m"]["n_rows"] == 20
    # Loads back into a scorer that scores identically.
    s = StrategyScorer.from_file(path)
    assert s.trained is True


def test_cli_refuses_without_data_source(capsys):
    rc = tr.main([])
    assert rc == 2
    assert "Refusing to run" in capsys.readouterr().out


def test_fetch_settled_rows_failsoft_no_pool():
    # No pool + no DB configured → fail-soft to [].
    class _BadPool:
        def acquire(self):
            raise RuntimeError("no db")

    assert _run(tr.fetch_settled_rows(pool=_BadPool())) == []


# ── A/B harness ───────────────────────────────────────────────────────────
def test_ab_compare_scorer_beats_router_on_constructed_case():
    rows = _dataset("btc")  # router_selected_rule = flip_hunter on every row
    s = StrategyScorer.from_model(tr.build_weights(rows))
    report = ab.compare(rows, s)
    btc = report.cells["BTC/5m"]
    assert btc.n_compared == 20
    # Router always picks flip_hunter (underdog): wins only on DOWN rows (10/20).
    assert btc.router_winrate == pytest.approx(0.5, abs=1e-9)
    # Scorer follows momentum → picks the winning side both halves.
    assert btc.scorer_winrate > btc.router_winrate
    assert btc.winrate_delta is not None and btc.winrate_delta > 0.0


def test_ab_counts_abstain_and_undecidable():
    # All three rules denied (edge below every threshold) → scorer abstains.
    rows = [_row("btc", 0.003, "UP", oracle_edge=0.001, oracle_status="computed")]
    s = StrategyScorer.from_model(tr.build_weights(_dataset("btc")))
    report = ab.compare(rows, s)
    assert report.cells["BTC/5m"].scorer_abstain == 1
    assert report.cells["BTC/5m"].n_compared == 0
    # Missing fav_side → undecidable (router rule not creditable).
    bad = dict(_row("btc", 0.003, "UP"))
    bad["fav_side"] = None
    report2 = ab.compare([bad], s)
    assert report2.overall.undecidable == 1


def test_ab_holdout_runs_out_of_sample():
    rows = _dataset("btc", n_each=20)  # 40 rows → splits cleanly
    report = ab.evaluate_holdout(rows, train_fraction=0.7)
    assert report.overall.n_compared > 0
    # format_report renders without raising.
    assert "router_wr" in ab.format_report(report)


# ── shadow wiring (signal_scan_job) ───────────────────────────────────────
class _Cand:
    def __init__(self, market_id, metadata):
        self.market_id = market_id
        self.condition_id = market_id
        self.metadata = metadata


def _shadow_md(asset="btc", momentum=0.003, oracle_edge=0.05, status="computed"):
    return {
        "factor_asset": asset,
        "factor_timeframe": "5m",
        "factor_momentum": momentum,
        "factor_volatility_sigma": 0.0001,
        "factor_liquidity_usdc": 1000.0,
        "factor_spread": 0.02,
        "factor_orderbook_depth_usdc": 1000.0,
        "factor_ttl_sec": 20.0,
        "factor_oracle_edge": oracle_edge,
        "factor_oracle_edge_status": status,
    }


def test_shadow_observe_first_rule_is_router_pick():
    from projects.polymarket.crusaderbot.services.signal_scan import signal_scan_job as job

    shadow: dict = {}
    md = _shadow_md()
    # close_sweep fires first (precedence) then flip_hunter for the same market.
    job._scorer_shadow_observe(shadow, _Cand("m1", md), "close_sweep")
    job._scorer_shadow_observe(shadow, _Cand("m1", md), "flip_hunter")
    assert shadow["m1"]["router_rule"] == "close_sweep"
    assert shadow["m1"]["firing_rules"] == ["close_sweep", "flip_hunter"]


def test_shadow_emit_logs_scorer_selected_rule(monkeypatch):
    from projects.polymarket.crusaderbot.services.signal_scan import signal_scan_job as job

    events: list = []
    monkeypatch.setattr(job.logger, "info", lambda ev, **kw: events.append((ev, kw)))
    # Force shadow on + a neutral (stub) scorer so the precedence ladder decides.
    monkeypatch.setattr(sc, "shadow_enabled", lambda: True)
    monkeypatch.setattr(sc, "active", lambda: False)
    monkeypatch.setattr(sc, "get_scorer", lambda **kw: StrategyScorer.neutral())

    shadow = {
        "m1": {
            "metadata": _shadow_md(),
            "condition_id": "m1",
            "firing_rules": ["close_sweep", "flip_hunter"],
            "router_rule": "close_sweep",
        }
    }
    _run(job._maybe_emit_scorer_shadow(shadow))
    shadow_events = [kw for ev, kw in events if ev == "scorer_shadow"]
    assert len(shadow_events) == 1
    payload = shadow_events[0]
    assert payload["scorer_selected_rule"] == "close_sweep"  # neutral → precedence
    assert payload["router_selected_rule"] == "close_sweep"
    assert payload["scorer_active"] is False  # selection stays router-controlled


def test_shadow_emit_respects_disabled_flag(monkeypatch):
    from projects.polymarket.crusaderbot.services.signal_scan import signal_scan_job as job

    events: list = []
    monkeypatch.setattr(job.logger, "info", lambda ev, **kw: events.append((ev, kw)))
    monkeypatch.setattr(sc, "shadow_enabled", lambda: False)
    shadow = {"m1": {"metadata": _shadow_md(), "condition_id": "m1",
                     "firing_rules": ["close_sweep"], "router_rule": "close_sweep"}}
    _run(job._maybe_emit_scorer_shadow(shadow))
    assert [kw for ev, kw in events if ev == "scorer_shadow"] == []
