"""Phase-2c-1b part 2 — robustness gate-wire tests.

Covers the downgrade-only live-guard (an UNTRADEABLE module can force a would-be
live trade to paper, never the reverse), the TradeSignal→GateContext threading,
and the TTL-cached ``untradeable_set`` source. Hermetic — no DB, no network.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from projects.polymarket.crusaderbot.domain.research import robustness as RB
from projects.polymarket.crusaderbot.domain.research.robustness import untradeable_set
from projects.polymarket.crusaderbot.domain.risk.gate import (
    _apply_robustness_downgrade,
    _passes_live_guards,
)
from projects.polymarket.crusaderbot.services.trade_engine.engine import (
    TradeEngine,
    TradeSignal,
)


def _all_pass_settings() -> SimpleNamespace:
    return SimpleNamespace(
        ENABLE_LIVE_TRADING=True,
        EXECUTION_PATH_VALIDATED=True,
        CAPITAL_MODE_CONFIRMED=True,
        RISK_CONTROLS_VALIDATED=True,
        SECURITY_HARDENING_VALIDATED=True,
        USE_REAL_CLOB=True,
    )


def _live_ctx(**over) -> SimpleNamespace:
    base = dict(role="admin", trading_mode="live", module_live_eligible=True)
    base.update(over)
    return SimpleNamespace(**base)


# ── robustness downgrade is SEPARATE from _passes_live_guards (Codex P1) ──
# The robustness flag must NOT live inside _passes_live_guards: a False there
# trips the user-level live fallback (persistent trading_mode flip). It is a
# standalone post-fallback step instead.
def test_passes_live_guards_ignores_robustness_flag():
    # _passes_live_guards is unchanged by the robustness flag — even an
    # ineligible module passes the guards (so the user-level fallback is NOT
    # tripped); the downgrade happens separately, after the fallback block.
    assert _passes_live_guards(_live_ctx(module_live_eligible=False), _all_pass_settings()) is True
    assert _passes_live_guards(_live_ctx(module_live_eligible=True), _all_pass_settings()) is True


def test_passes_live_guards_still_blocks_on_real_guard_failure():
    s = _all_pass_settings()
    s.USE_REAL_CLOB = False
    assert _passes_live_guards(_live_ctx(), s) is False


def test_robustness_downgrade_live_to_paper_when_untradeable():
    assert _apply_robustness_downgrade("live", _live_ctx(module_live_eligible=False)) == "paper"


def test_robustness_downgrade_noop_when_eligible():
    assert _apply_robustness_downgrade("live", _live_ctx(module_live_eligible=True)) == "live"


def test_robustness_downgrade_never_upgrades_paper():
    # An ineligible module on a paper trade stays paper (never upgrades to live).
    assert _apply_robustness_downgrade("paper", _live_ctx(module_live_eligible=False)) == "paper"
    assert _apply_robustness_downgrade("paper", _live_ctx(module_live_eligible=True)) == "paper"


# ── TradeSignal → GateContext threading ───────────────────────────────────
def _signal_ns(module_live_eligible: bool) -> SimpleNamespace:
    # _build_gate_context only reads attributes — a namespace is sufficient.
    fields = dict(
        user_id="u", telegram_user_id=1, role="admin", auto_trade_on=True,
        paused=False, market_id="m", side="yes", proposed_size_usdc=10,
        price=0.5, market_liquidity=1000.0, market_status="active", edge_bps=100,
        signal_ts=None, idempotency_key="k", strategy_type="sharp_money",
        risk_profile="balanced", daily_loss_override=None, trading_mode="live",
        user_min_liquidity=0.0, max_drawdown_pct=None, live_capital_cap_usdc=0.0,
        max_concurrent_override=None, bypass_auto_trade_check=False,
        module_live_eligible=module_live_eligible,
    )
    return SimpleNamespace(**fields)


def test_signal_threads_eligibility_into_gate_context():
    ctx_block = TradeEngine._build_gate_context(_signal_ns(False))
    assert ctx_block.module_live_eligible is False
    ctx_ok = TradeEngine._build_gate_context(_signal_ns(True))
    assert ctx_ok.module_live_eligible is True


def test_trade_signal_defaults_eligible_true():
    # Backward-compat: existing callers that omit the field get live-eligible.
    sig = TradeSignal(
        user_id="u", telegram_user_id=1, role="user", auto_trade_on=True,
        paused=False, market_id="m", market_question=None, yes_token_id=None,
        no_token_id=None, side="yes", proposed_size_usdc=10, price=0.5,
        market_liquidity=1000.0, market_status="active", idempotency_key="k",
        strategy_type="x", risk_profile="balanced", trading_mode="paper",
    )
    assert sig.module_live_eligible is True


# ── untradeable_set source ────────────────────────────────────────────────
class _Conn:
    def __init__(self, *, rows=None, raise_exc=False):
        self.rows = rows or []
        self.raise_exc = raise_exc
        self.calls = 0

    async def fetch(self, sql, *a):
        self.calls += 1
        if self.raise_exc:
            raise RuntimeError("db down")
        return self.rows


class _Pool:
    def __init__(self, conn):
        self._c = conn

    def acquire(self):
        c = self._c

        class _Ctx:
            async def __aenter__(self_inner):
                return c

            async def __aexit__(self_inner, *a):
                return False

        return _Ctx()


def _patch(conn):
    return patch.object(RB, "get_pool", return_value=_Pool(conn))


def test_untradeable_set_aggregates_pairs():
    RB._untradeable_cache.clear()
    conn = _Conn(rows=[
        {"module": "closing_edge", "risk_profile": "balanced"},
        {"module": "sharp_money", "risk_profile": "aggressive"},
    ])
    with _patch(conn):
        out = asyncio.run(untradeable_set(mode="paper"))
    assert out == frozenset({("closing_edge", "balanced"), ("sharp_money", "aggressive")})


def test_untradeable_set_caches_within_ttl():
    RB._untradeable_cache.clear()
    conn = _Conn(rows=[{"module": "m", "risk_profile": "balanced"}])
    with _patch(conn):
        asyncio.run(untradeable_set(mode="paper"))
        asyncio.run(untradeable_set(mode="paper"))
    assert conn.calls == 1  # second call served from cache


def test_untradeable_set_failsoft_empty():
    RB._untradeable_cache.clear()
    conn = _Conn(raise_exc=True)
    with _patch(conn):
        out = asyncio.run(untradeable_set(mode="paper"))
    assert out == frozenset()  # empty → never over-blocks
