"""Lane 2 — per-user selection diversity + raised concurrency caps.

Hermetic. No DB/HTTP. Exercises signal_evaluator._diversify_order (the fix
that stops every subscriber from converging on the same published prefix)
and pins the per-profile max_concurrent caps.
"""
from __future__ import annotations

from datetime import datetime, timezone

from projects.polymarket.crusaderbot.domain.risk.constants import PROFILES
from projects.polymarket.crusaderbot.domain.strategy.types import SignalCandidate
from projects.polymarket.crusaderbot.services.signal_feed import signal_evaluator


def _cand(market_id: str) -> SignalCandidate:
    return SignalCandidate(
        market_id=market_id,
        condition_id=market_id,
        side="YES",
        confidence=0.6,
        suggested_size_usdc=10.0,
        strategy_name="signal_following",
        signal_ts=datetime.now(timezone.utc),
    )


def _order(candidates, user_id) -> list[str]:
    return [c.market_id for c in signal_evaluator._diversify_order(candidates, user_id)]


# --------------------------- diversity ---------------------------

def test_two_users_get_different_orderings():
    """The same published set must not surface in identical order for two
    users — that is what made the bot trade 'the same 5' for everyone."""
    cands = [_cand(f"0xmkt{i:03d}") for i in range(40)]
    a = _order(cands, "11111111-1111-1111-1111-111111111111")
    b = _order(cands, "22222222-2222-2222-2222-222222222222")
    assert a != b
    # The cap-limited prefix (what actually gets entered) must differ too.
    assert a[:12] != b[:12]


def test_same_user_ordering_is_stable():
    """Deterministic per (user, market) so a user does not churn positions
    between scan ticks."""
    cands = [_cand(f"0xmkt{i:03d}") for i in range(40)]
    uid = "33333333-3333-3333-3333-333333333333"
    assert _order(cands, uid) == _order(list(reversed(cands)), uid)


def test_diversify_preserves_the_full_set():
    """No candidate is dropped or duplicated — only the order changes."""
    cands = [_cand(f"0xmkt{i:03d}") for i in range(40)]
    out = _order(cands, "44444444-4444-4444-4444-444444444444")
    assert sorted(out) == sorted(c.market_id for c in cands)


def test_empty_candidates_safe():
    assert signal_evaluator._diversify_order([], "u") == []


# --------------------------- caps ---------------------------

def test_concurrency_caps_raised():
    assert PROFILES["conservative"]["max_concurrent"] == 5
    assert PROFILES["balanced"]["max_concurrent"] == 12
    assert PROFILES["aggressive"]["max_concurrent"] == 20
    assert PROFILES["custom"]["max_concurrent"] == 12


def test_fixed_risk_limits_unchanged():
    """Cap raise must not have touched the hard-wired risk fences."""
    assert PROFILES["aggressive"]["kelly"] == 0.25
    assert PROFILES["aggressive"]["max_pos_pct"] == 0.10
