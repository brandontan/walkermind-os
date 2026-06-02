"""Tests for the candle_auto lifecycle-router preset (Smart Strike).

candle_auto is an additive 4th candle preset whose internal key stays
``candle_auto`` (the user-facing label is "Smart Strike"). It routes to the same
``late_entry_v3`` engine as the three single-rule candle presets, but per market
picks whichever rule fits the candle's stage and stamps that rule's exit (TP/SL +
force-exit) into the candidate metadata so each entry keeps its own exit.

These tests pin:
  * preset wiring (registered, visible, routes to late_entry_v3, NOT a member of
    _CANDLE_PRESETS so the single-rule param dispatch is unaffected),
  * the per-rule TP/SL source (canonical domain PRESETS — no magic numbers),
  * the router merge: scans each rule, dedups by market_id with close_sweep >
    safe_close > flip_hunter precedence, stamps candle_rule + applied tp/sl,
  * the single-preset path stays a single scan() with no router stamping.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from projects.polymarket.crusaderbot.domain.preset import presets as dp
from projects.polymarket.crusaderbot.domain.strategy.types import SignalCandidate
from projects.polymarket.crusaderbot.services.signal_scan import signal_scan_job as ssj


_CANDLE_AUTO = "candle_auto"


def _cand(market_id: str) -> SignalCandidate:
    return SignalCandidate(
        market_id=market_id,
        condition_id=market_id,
        side="YES",
        confidence=0.5,
        suggested_size_usdc=5.0,
        strategy_name="late_entry_v3",
        signal_ts=datetime.now(timezone.utc),
        metadata={"force_exit_at_rem_sec": 0.0},
    )


class _FakeStrat:
    """Stand-in for late_entry_v3: returns candidates per rule, keyed off the
    distinguishing kwargs the router forwards (underdog_mode / size_time_decay /
    min_entry_sec). Records every scan() call for assertions."""

    def __init__(self, by_rule: dict[str, list[SignalCandidate]]):
        self.by_rule = by_rule
        self.calls: list[dict] = []

    async def scan(self, market_filters, user_ctx, **kw):
        self.calls.append(kw)
        if kw.get("underdog_mode"):
            rule = "flip_hunter"
        elif kw.get("size_time_decay"):
            rule = "close_sweep"
        else:
            rule = "safe_close"
        return list(self.by_rule.get(rule, []))


def _fake_resolve(preset: str, tf):
    """Deterministic preset-param resolver (no config dependency).

    Each rule carries the distinguishing kwarg _FakeStrat keys off so we do not
    rely on .env / get_settings in CI."""
    base = {"min_ask_diff": 0.05, "fav_price_min": 0.50, "fav_price_max": 0.70}
    if preset == "close_sweep":
        return {**base, "entry_window_sec": 35.0, "size_time_decay": True}
    if preset == "safe_close":
        return {**base, "entry_window_sec": 60.0, "min_entry_sec": 30.0,
                "force_exit_at_rem_sec": 30.0}
    if preset == "flip_hunter":
        return {**base, "entry_window_sec": 180.0, "min_entry_sec": 60.0,
                "underdog_mode": True, "force_exit_at_rem_sec": 0.0}
    return base


# ---------------------------------------------------------------------------
# Preset wiring
# ---------------------------------------------------------------------------

def test_candle_auto_registered_and_visible():
    assert _CANDLE_AUTO in dp.PRESETS
    assert _CANDLE_AUTO in dp.VISIBLE_PRESET_ORDER
    assert _CANDLE_AUTO in dp.CANDLE_PRESET_KEYS
    assert dp.PRESETS[_CANDLE_AUTO].name == "Smart Strike"
    # routes to the same engine as the single-rule candle presets
    assert dp.PRESETS[_CANDLE_AUTO].strategies == ("late_entry_v3",)


def test_candle_auto_scanner_gating():
    # routed to late_entry_v3 by the scanner gate
    assert ssj._PRESET_ALLOWED.get(_CANDLE_AUTO) == frozenset({"late_entry_v3"})
    # treated as a candle preset for window-fetch + fast-loop gates
    assert _CANDLE_AUTO in ssj._ALL_CANDLE_PRESETS
    # but NOT a member of _CANDLE_PRESETS — that set drives the single-rule
    # _resolve_preset_params dispatch; candle_auto must never fall through it
    # (it would otherwise resolve to flip_hunter params).
    assert _CANDLE_AUTO not in ssj._CANDLE_PRESETS


def test_candle_auto_rule_tpsl_from_canonical_presets():
    for rule in ("close_sweep", "safe_close", "flip_hunter"):
        tp, sl = ssj._candle_auto_rule_tpsl(rule)
        assert tp == pytest.approx(dp.PRESETS[rule].tp_pct)
        assert sl == pytest.approx(dp.PRESETS[rule].sl_pct)
    # unknown rule → (None, None) → user-level tp/sl applies unchanged
    assert ssj._candle_auto_rule_tpsl("nope") == (None, None)


# ---------------------------------------------------------------------------
# Router merge / dedup / per-rule stamping
# ---------------------------------------------------------------------------

def test_router_merges_dedups_and_stamps(monkeypatch):
    monkeypatch.setattr(ssj, "_resolve_preset_params", _fake_resolve)
    # close_sweep claims M_CLOSE + the overlap market; safe_close ALSO emits the
    # overlap market (favorite side) — close_sweep must win precedence. flip is a
    # separate market.
    strat = _FakeStrat({
        "close_sweep": [_cand("M_CLOSE"), _cand("M_OVERLAP")],
        "safe_close":  [_cand("M_OVERLAP"), _cand("M_SAFE")],
        "flip_hunter": [_cand("M_FLIP")],
    })

    out = asyncio.run(
        ssj._scan_late_entry_for_preset(strat, _CANDLE_AUTO, "5m", object(), object())
    )

    by_market = {c.market_id: c for c in out}
    # four distinct markets — the overlap market is deduped to one entry
    assert set(by_market) == {"M_CLOSE", "M_OVERLAP", "M_SAFE", "M_FLIP"}
    # all three single rules were scanned
    assert len(strat.calls) == 3

    # precedence: close_sweep wins the overlapping market
    assert by_market["M_OVERLAP"].metadata["candle_rule"] == "close_sweep"
    assert by_market["M_SAFE"].metadata["candle_rule"] == "safe_close"
    assert by_market["M_FLIP"].metadata["candle_rule"] == "flip_hunter"

    # per-rule TP/SL stamped from canonical PRESETS so the exit stays per-rule
    flip = by_market["M_FLIP"]
    assert flip.metadata["applied_tp_pct"] == pytest.approx(dp.PRESETS["flip_hunter"].tp_pct)
    assert flip.metadata["applied_sl_pct"] == pytest.approx(dp.PRESETS["flip_hunter"].sl_pct)
    close = by_market["M_CLOSE"]
    assert close.metadata["applied_tp_pct"] == pytest.approx(dp.PRESETS["close_sweep"].tp_pct)


def test_router_subrule_failure_isolated(monkeypatch):
    monkeypatch.setattr(ssj, "_resolve_preset_params", _fake_resolve)

    class _PartialStrat(_FakeStrat):
        async def scan(self, market_filters, user_ctx, **kw):
            if kw.get("size_time_decay"):  # close_sweep rule blows up
                raise RuntimeError("boom")
            return await super().scan(market_filters, user_ctx, **kw)

    strat = _PartialStrat({
        "safe_close":  [_cand("M_SAFE")],
        "flip_hunter": [_cand("M_FLIP")],
    })
    out = asyncio.run(
        ssj._scan_late_entry_for_preset(strat, _CANDLE_AUTO, "5m", object(), object())
    )
    # close_sweep failed, but safe_close + flip_hunter still produced candidates
    assert {c.market_id for c in out} == {"M_SAFE", "M_FLIP"}


def test_single_preset_path_no_router_stamp(monkeypatch):
    monkeypatch.setattr(ssj, "_resolve_preset_params", _fake_resolve)
    strat = _FakeStrat({"close_sweep": [_cand("M1")]})
    out = asyncio.run(
        ssj._scan_late_entry_for_preset(strat, "close_sweep", "5m", object(), object())
    )
    assert len(strat.calls) == 1                 # one scan, not three
    assert len(out) == 1
    # single-rule path must NOT stamp router-only keys
    assert "candle_rule" not in out[0].metadata
    assert "applied_tp_pct" not in out[0].metadata
