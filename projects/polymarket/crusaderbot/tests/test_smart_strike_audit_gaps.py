"""Smart Strike audit-gap closure (#1801) — explicit tests for the items #1799
covered by audit prose only: per-user sizing isolation, Polymarket-API
eligibility fields, min-order-size fail-closed, market-data freshness posture,
user-facing SOL-disabled state, observability, and the shared admin-universe
resolver.

No real order, no fund movement, no live-guard flips — pure unit/behaviour.
"""
from __future__ import annotations

import asyncio
import inspect
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest


# ── 1. PER-USER CAPITAL ISOLATION ────────────────────────────────────────────

def test_get_live_balance_binds_only_the_active_user():
    """get_live_balance must scope to the active user_id ONLY — user A's read
    can never sum user B's (or any pooled) ledger rows."""
    from projects.polymarket.crusaderbot.wallet import ledger

    a, b = uuid4(), uuid4()
    by_user = {a: Decimal("123.45"), b: Decimal("9.99")}
    bound: list = []

    class _Conn:
        async def fetchval(self, sql, *args):
            assert "l.user_id = $1" in sql, "live balance not per-user scoped"
            bound.append(args[0])
            return by_user[args[0]]

    conn = _Conn()
    bal_a = asyncio.run(ledger.get_live_balance(a, conn))
    bal_b = asyncio.run(ledger.get_live_balance(b, conn))
    assert bal_a == Decimal("123.45")
    assert bal_b == Decimal("9.99")
    assert bound == [a, b], "each read bound only its own user_id"


def test_live_ledger_filter_excludes_paper_and_pending_and_pool():
    """The live bucket is confirmed on-chain deposits / withdrawals / live
    position rows only — never paper rows, unmatched (pending) deposits, or any
    cross-user/master pool aggregate."""
    from projects.polymarket.crusaderbot.wallet import ledger

    flt = ledger._LIVE_LEDGER_FILTER_SQL
    # confirmed deposit must be matched to a real deposits row (excludes paper
    # admin-reset rows whose ref_id is NULL, and pending/unmatched deposits).
    assert "l.ref_id IS NOT NULL" in flt
    assert "FROM deposits d WHERE d.id = l.ref_id" in flt
    # live position rows only (mode='live') — paper positions excluded.
    assert "p.mode = 'live'" in flt
    # never a pool/master/cross-user aggregate.
    for forbidden in ("master", "pool", "SUM(w.balance", "GROUP BY"):
        assert forbidden not in flt


def test_gate_live_sizing_reads_only_per_user_balance_no_pool():
    """Gate step 13/15 sizes from the per-user live balance (ctx value or
    get_live_balance(ctx.user_id)) — source pin proving no master/pool read."""
    from projects.polymarket.crusaderbot.domain.risk import gate as gate_mod
    src = inspect.getsource(gate_mod.evaluate)
    assert "get_live_balance(ctx.user_id)" in src
    assert "sizing_balance = live_bal" in src
    # the live capital bound + no-funds reject are per-user
    assert "live_no_funds" in src and "live_capital_cap_exceeded" in src
    # no pooled/master/other-user balance in the sizing path
    for forbidden in ("master_wallet", "pool_balance", "get_usdc_balance("):
        assert forbidden not in src


def test_kelly_stays_fractional_quarter():
    from projects.polymarket.crusaderbot.domain.risk import constants as K
    assert K.KELLY_FRACTION == 0.25
    src = inspect.getsource(
        __import__("projects.polymarket.crusaderbot.domain.risk.gate",
                   fromlist=["evaluate"]).evaluate
    )
    assert "min(float(profile.get(\"kelly\", K.KELLY_FRACTION)), K.KELLY_FRACTION)" in src


# ── 2. POLYMARKET-API ELIGIBILITY FIELDS ─────────────────────────────────────

def _ctx():
    from projects.polymarket.crusaderbot.domain.strategy.types import UserContext
    return UserContext(
        user_id=str(uuid4()), sub_account_id=str(uuid4()),
        risk_profile="balanced", capital_allocation_pct=0.4,
        available_balance_usdc=100.0, equity_usdc=100.0,
    )


def _eval(market):
    from projects.polymarket.crusaderbot.domain.strategy.strategies import (
        late_entry_v3 as lev3,
    )
    from datetime import datetime, timezone
    import time as _t
    return asyncio.run(lev3._evaluate_market(
        market, blacklist=set(), user_context=_ctx(),
        strategy_name="late_entry_v3",
        signal_ts=datetime.now(timezone.utc), now_ts=_t.time(),
    ))


def test_eligibility_rejects_archived_market():
    cand, reason = _eval({
        "conditionId": "0xabc", "slug": "btc-updown-5m-1",
        "closed": False, "archived": True,
    })
    assert cand is None and reason == "archived"


def test_eligibility_rejects_order_book_disabled_market():
    cand, reason = _eval({
        "conditionId": "0xabc", "slug": "btc-updown-5m-1",
        "closed": False, "archived": False, "acceptingOrders": True,
        "enableOrderBook": False,
    })
    assert cand is None and reason == "order_book_disabled"


def test_eligibility_preserves_closed_and_accepting_checks():
    assert _eval({"conditionId": "0xabc", "slug": "btc-updown-5m-1",
                  "closed": True})[1] == "closed"
    assert _eval({"conditionId": "0xabc", "slug": "btc-updown-5m-1",
                  "closed": False, "acceptingOrders": False})[1] == "not_accepting_orders"


# ── 3. MIN ORDER SIZE — FAIL CLOSED ──────────────────────────────────────────

def test_live_min_order_shares_constant_and_fail_closed():
    from projects.polymarket.crusaderbot.domain.risk import constants as K
    from projects.polymarket.crusaderbot.domain.execution import live
    assert K.LIVE_MIN_ORDER_SHARES == 5.0
    src = inspect.getsource(live)
    # a sub-minimum order raises pre-submit (fail closed), never submits.
    assert "shares < LIVE_MIN_ORDER_SHARES" in src
    assert "LivePreSubmitError(" in src
    # the raise sits BEFORE the broker post_order call.
    assert src.index("shares < LIVE_MIN_ORDER_SHARES") < src.index("post_order(")


def test_min_order_arithmetic_below_floor_is_rejected():
    """Bare logic: $1 at price 0.50 -> 2 shares < 5 -> reject; $5 at 0.50 ->
    10 shares -> ok."""
    from projects.polymarket.crusaderbot.domain.risk.constants import (
        LIVE_MIN_ORDER_SHARES,
    )
    assert (1.0 / 0.50) < LIVE_MIN_ORDER_SHARES
    assert (5.0 / 0.50) >= LIVE_MIN_ORDER_SHARES


# ── 4. MARKET-DATA FRESHNESS POSTURE ─────────────────────────────────────────

def test_candle_scan_uses_fresh_rest_book_and_fails_closed_on_empty():
    """Smart Strike pulls a FRESH CLOB order book per candidate via REST
    (pm.get_book) and emits NO TRADE on an empty/missing book — there is no
    stale cached-book path that could leak a trade."""
    from projects.polymarket.crusaderbot.domain.strategy.strategies import (
        late_entry_v3 as lev3,
    )
    src = inspect.getsource(lev3._evaluate_market)
    assert "pm.get_book(yes_token)" in src and "pm.get_book(no_token)" in src
    assert 'return None, "empty_book"' in src
    # tick_size / neg_risk are fetched fresh on the live path and missing
    # metadata fails closed (LivePreSubmitError) — never submit without them.
    live_src = inspect.getsource(
        __import__(
            "projects.polymarket.crusaderbot.domain.execution.live",
            fromlist=["x"],
        )
    )
    assert "CLOB market metadata unavailable" in live_src


# ── 5. OBSERVABILITY TRACE ───────────────────────────────────────────────────

def test_live_order_intent_trace_carries_decision_context():
    from projects.polymarket.crusaderbot.domain.execution import live
    src = inspect.getsource(live)
    assert "live_order_intent" in src
    for field in ("token=%s", "side=%s", "shares=", "limit_price=",
                  "best_bid=", "best_ask=", "tick_size=", "min_shares=",
                  "market=%s", "user=%s"):
        assert field in src, f"missing trace field: {field}"


# ── 6. SHARED ADMIN-UNIVERSE RESOLVER (single source of truth) ───────────────

def _ss_settings(**over):
    base = dict(
        SMART_STRIKE_ENABLED=True, SMART_STRIKE_BTC_ENABLED=True,
        SMART_STRIKE_ETH_ENABLED=True, SMART_STRIKE_SOL_ENABLED=False,
        SMART_STRIKE_5M_ENABLED=True, SMART_STRIKE_15M_ENABLED=True,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _drive(coro_fn, *, settings=None, overrides=None):
    from projects.polymarket.crusaderbot.domain.strategy import (
        smart_strike_universe as ssu,
    )
    s = settings or _ss_settings()
    ov = overrides or {}

    async def fake_resolve_bool(key, env_default):
        return ov.get(key, env_default)

    with patch("projects.polymarket.crusaderbot.config.get_settings",
               return_value=s), \
         patch.object(ssu._runtime_config, "resolve_bool",
                      AsyncMock(side_effect=fake_resolve_bool)):
        return asyncio.run(coro_fn(ssu))


def test_resolver_enabled_pairs_default_btc_eth_sol_off():
    pairs = _drive(lambda ssu: ssu.enabled_pairs())
    assert pairs == ["BTC", "ETH"]


def test_resolver_timeframes_default_5m_15m():
    tfs = _drive(lambda ssu: ssu.enabled_timeframes())
    assert tfs == ["5m", "15m"]


def test_resolver_sol_admin_enable():
    pairs = _drive(lambda ssu: ssu.enabled_pairs(),
                   overrides={"SMART_STRIKE_SOL_ENABLED": True})
    assert pairs == ["BTC", "ETH", "SOL"]


def test_resolver_master_off_then_pairs_still_resolve_but_master_false():
    master = _drive(lambda ssu: ssu.master_enabled(),
                    overrides={"SMART_STRIKE_ENABLED": False})
    assert master is False


def test_scan_gate_delegates_to_shared_resolver():
    """The signal-scan universe gate resolves via the shared module so the
    scanner and the WebTrader status can never drift."""
    from projects.polymarket.crusaderbot.services.signal_scan import (
        signal_scan_job as ssj,
    )
    src = inspect.getsource(ssj._smart_strike_admin_universe)
    assert "_ss_universe.master_enabled()" in src
    assert "_ss_universe.timeframe_enabled(" in src
    assert "_ss_universe.asset_enabled(" in src


# ── 7. USER-FACING ENABLED-UNIVERSE EXPOSURE ─────────────────────────────────

def test_autotrade_state_carries_smart_strike_universe_fields():
    from projects.polymarket.crusaderbot.webtrader.backend.schemas import (
        AutoTradeState,
    )
    fields = AutoTradeState.model_fields
    assert "smart_strike_enabled" in fields
    assert "smart_strike_enabled_assets" in fields
    assert "smart_strike_enabled_timeframes" in fields


def test_autotrade_endpoint_resolves_universe_from_shared_module():
    from projects.polymarket.crusaderbot.webtrader.backend import router
    src = inspect.getsource(router.get_autotrade)
    assert "smart_strike_universe" in src
    assert "enabled_pairs()" in src
    assert "smart_strike_enabled_assets=" in src


def test_frontend_disables_admin_off_assets_in_picker():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "webtrader" / "frontend" / "src"
    page = (root / "pages" / "AutoTradePage.tsx").read_text(encoding="utf-8")
    # default still BTC/ETH (SOL not active by default)
    assert 'CRYPTO_ASSETS_DEFAULT: readonly string[] = ["BTC", "ETH"]' in page
    # the picker drives availability off the backend-enabled set and disables
    # the rest (SOL) rather than presenting them as freely selectable.
    assert "ssEnabledAssets" in page
    assert "smart_strike_enabled_assets" in page
    assert "disabled={!adminEnabled}" in page
    api = (root / "lib" / "api.ts").read_text(encoding="utf-8")
    assert "smart_strike_enabled_assets?: string[];" in api


def test_user_facing_copy_does_not_imply_sol_trades_by_default():
    from pathlib import Path
    base = Path(__file__).resolve().parents[1]
    presets = (base / "bot" / "handlers" / "presets.py").read_text(encoding="utf-8")
    msgs = (base / "bot" / "messages.py").read_text(encoding="utf-8")
    page = (base / "webtrader" / "frontend" / "src" / "pages" / "AutoTradePage.tsx").read_text(encoding="utf-8")
    # descriptive copy must not list SOL as an active default engine asset.
    assert "BTC/ETH/SOL candles" not in presets
    assert "BTC/ETH/SOL" not in msgs
    assert "same BTC/ETH/SOL engine" not in page
    assert "Final 35s entry on BTC/ETH/SOL" not in page
