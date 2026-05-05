"""Hermetic tests for the P3b copy-trade strategy plane.

Coverage:
    * scaler.scale_size — proportional rule, hard cap, $1 floor, degenerate inputs
    * wallet_watcher    — rate limiter, 5 s timeout, error swallowing,
                          fetch_leader_open_condition_ids
    * CopyTradeStrategy — registration, scan empty path, scan dedup, scan stale
                          window, scan size scaling skip, evaluate_exit branches,
                          default_tp_sl
    * Telegram handler  — wallet validation, MAX target cap, normalisation,
                          truncate helper

No DB, no broker, no Telegram network. Database access is patched via the
asyncpg pool acquire context manager so the strategy + handler can be exercised
end-to-end on the request boundary without spinning up Postgres.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest

from projects.polymarket.crusaderbot.domain.strategy import (
    StrategyRegistry,
    bootstrap_default_strategies,
)
from projects.polymarket.crusaderbot.domain.strategy.strategies.copy_trade import (
    CopyTradeStrategy,
    _coerce_float,
    _normalise_side,
    _parse_trade_timestamp,
)
from projects.polymarket.crusaderbot.domain.strategy.types import (
    MarketFilters,
    UserContext,
)
from projects.polymarket.crusaderbot.services.copy_trade import (
    GLOBAL_RATE_LIMIT_INTERVAL_SEC,
    MIN_TRADE_SIZE_USDC,
    POLYMARKET_FETCH_TIMEOUT_SEC,
    scale_size,
)
from projects.polymarket.crusaderbot.services.copy_trade import (
    wallet_watcher as ww,
)
from projects.polymarket.crusaderbot.bot.handlers.copy_trade import (
    MAX_COPY_TARGETS_PER_USER,
    _normalise_wallet,
    _truncate_wallet,
)
from projects.polymarket.crusaderbot.bot.keyboards.copy_trade import (
    copy_targets_list_kb,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_registry():
    StrategyRegistry._reset_for_tests()
    yield
    StrategyRegistry._reset_for_tests()


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Each test starts with a fresh module-global rate limiter timestamp."""
    ww._last_request_at = 0.0
    yield
    ww._last_request_at = 0.0


# ---------------------------------------------------------------------------
# Constants sanity
# ---------------------------------------------------------------------------


def test_module_constants_match_spec():
    assert MIN_TRADE_SIZE_USDC == 1.0
    assert POLYMARKET_FETCH_TIMEOUT_SEC == 5.0
    assert GLOBAL_RATE_LIMIT_INTERVAL_SEC == 1.0
    assert MAX_COPY_TARGETS_PER_USER == 3


# ---------------------------------------------------------------------------
# scaler.scale_size
# ---------------------------------------------------------------------------


def test_scale_size_proportional_rule():
    # leader bankroll 10_000, leader trade 100, user available 1000.
    # proportional = (1000 / 10000) * 100 = 10. cap (1000 * 0.5 = 500) does
    # not bind. floor satisfied. Expect 10.0.
    out = scale_size(
        leader_size=100.0, leader_bankroll=10_000.0,
        user_available=1000.0, max_position_pct=0.5,
    )
    assert out == pytest.approx(10.0)


def test_scale_size_position_cap_binds_when_proportional_too_large():
    # proportional = (100 / 100) * 50 = 50. cap = 100 * 0.10 = 10. Cap binds.
    out = scale_size(
        leader_size=50.0, leader_bankroll=100.0,
        user_available=100.0, max_position_pct=0.10,
    )
    assert out == pytest.approx(10.0)


def test_scale_size_below_floor_returns_zero():
    # proportional = (5 / 100) * 5 = 0.25 — below the $1 floor, must skip.
    out = scale_size(
        leader_size=5.0, leader_bankroll=100.0,
        user_available=5.0, max_position_pct=1.0,
    )
    assert out == 0.0


def test_scale_size_at_exactly_one_dollar_passes_floor():
    # cap = 1.0, proportional = 1.0 — equality is allowed, NOT a skip.
    out = scale_size(
        leader_size=10.0, leader_bankroll=100.0,
        user_available=10.0, max_position_pct=0.10,
    )
    assert out == pytest.approx(1.0)


@pytest.mark.parametrize(
    "leader, bankroll, avail, pct",
    [
        (0.0, 100.0, 100.0, 0.5),     # zero leader trade
        (-1.0, 100.0, 100.0, 0.5),    # negative leader trade
        (10.0, 0.0, 100.0, 0.5),      # zero bankroll (div-by-zero protection)
        (10.0, -1.0, 100.0, 0.5),     # negative bankroll
        (10.0, 100.0, 0.0, 0.5),      # zero user balance
        (10.0, 100.0, -1.0, 0.5),     # negative user balance
        (10.0, 100.0, 100.0, 0.0),    # zero position cap pct
        (10.0, 100.0, 100.0, -0.1),   # negative position cap pct
        (10.0, 100.0, 100.0, 1.5),    # cap pct > 1.0 (out of contract range)
    ],
)
def test_scale_size_degenerate_inputs_return_zero(leader, bankroll, avail, pct):
    assert scale_size(leader, bankroll, avail, pct) == 0.0


# ---------------------------------------------------------------------------
# wallet_watcher
# ---------------------------------------------------------------------------


def test_fetch_recent_wallet_trades_returns_list():
    async def fake_get_user_activity(wallet, limit=20):
        return [{"transactionHash": "0x1", "side": "BUY"}]

    with patch.object(ww.pm, "get_user_activity", fake_get_user_activity):
        out = asyncio.run(ww.fetch_recent_wallet_trades("0xabc", limit=10))
    assert out == [{"transactionHash": "0x1", "side": "BUY"}]


def test_fetch_recent_wallet_trades_blank_address_skips_call():
    called = {"n": 0}

    async def fake_get_user_activity(wallet, limit=20):
        called["n"] += 1
        return []

    with patch.object(ww.pm, "get_user_activity", fake_get_user_activity):
        out = asyncio.run(ww.fetch_recent_wallet_trades("", limit=10))
    assert out == [] and called["n"] == 0


def test_fetch_recent_wallet_trades_swallows_timeout():
    async def fake_get_user_activity(wallet, limit=20):
        await asyncio.sleep(10)  # would exceed 5s; wait_for cancels
        return [{"x": 1}]

    with patch.object(ww.pm, "get_user_activity", fake_get_user_activity):
        with patch.object(ww, "POLYMARKET_FETCH_TIMEOUT_SEC", 0.05):
            out = asyncio.run(ww.fetch_recent_wallet_trades("0xabc", limit=5))
    assert out == []


def test_fetch_recent_wallet_trades_swallows_unexpected_error():
    async def fake_get_user_activity(wallet, limit=20):
        raise RuntimeError("api down")

    with patch.object(ww.pm, "get_user_activity", fake_get_user_activity):
        out = asyncio.run(ww.fetch_recent_wallet_trades("0xabc", limit=5))
    assert out == []


def test_fetch_recent_wallet_trades_rejects_non_list_response():
    async def fake_get_user_activity(wallet, limit=20):
        return {"data": []}  # caller does not expect a dict

    with patch.object(ww.pm, "get_user_activity", fake_get_user_activity):
        out = asyncio.run(ww.fetch_recent_wallet_trades("0xabc", limit=5))
    assert out == []


def test_rate_limit_serialises_back_to_back_calls():
    async def fake_get_user_activity(wallet, limit=20):
        return []

    async def runner():
        # Simulate two calls back-to-back; second must wait at least the
        # interval before _last_request_at is bumped again.
        await ww.fetch_recent_wallet_trades("0xabc", limit=5)
        t0 = time.monotonic()
        await ww.fetch_recent_wallet_trades("0xabc", limit=5)
        return time.monotonic() - t0

    with patch.object(ww, "GLOBAL_RATE_LIMIT_INTERVAL_SEC", 0.05):
        with patch.object(ww.pm, "get_user_activity", fake_get_user_activity):
            elapsed = asyncio.run(runner())
    # Allow generous slack — the assertion is "at least the interval", not
    # "exactly the interval".
    assert elapsed >= 0.04


def test_fetch_leader_open_condition_ids_filters_buys_only():
    # Newest-first walk: cond_a's first action is BUY (still open), cond_b's
    # first action is SELL (already exited).
    trades = [
        {"conditionId": "cond_a", "side": "BUY"},
        {"conditionId": "cond_b", "side": "SELL"},
        {"conditionId": "cond_a", "side": "BUY"},
        {"conditionId": "cond_b", "side": "BUY"},
    ]

    async def fake_fetch(wallet, limit=50):
        return trades

    with patch.object(ww, "fetch_recent_wallet_trades", fake_fetch):
        out = asyncio.run(ww.fetch_leader_open_condition_ids("0xabc"))
    assert out == {"cond_a"}


def test_fetch_leader_open_condition_ids_empty_when_no_wallet():
    out = asyncio.run(ww.fetch_leader_open_condition_ids(""))
    assert out == set()


def test_fetch_leader_open_condition_ids_handles_no_trades():
    async def fake_fetch(wallet, limit=50):
        return []

    with patch.object(ww, "fetch_recent_wallet_trades", fake_fetch):
        out = asyncio.run(ww.fetch_leader_open_condition_ids("0xabc"))
    assert out == set()


# ---------------------------------------------------------------------------
# CopyTradeStrategy — registration + bootstrap
# ---------------------------------------------------------------------------


def test_copy_trade_strategy_default_tp_sl_matches_spec():
    tp, sl = CopyTradeStrategy().default_tp_sl()
    assert (tp, sl) == (0.25, 0.10)


def test_bootstrap_registers_copy_trade():
    reg = bootstrap_default_strategies()
    assert reg.get("copy_trade").name == "copy_trade"
    assert reg.get("copy_trade").version == "1.0.0"
    assert set(reg.get("copy_trade").risk_profile_compatibility) == {
        "conservative", "balanced", "aggressive",
    }


def test_bootstrap_is_idempotent():
    reg = bootstrap_default_strategies()
    bootstrap_default_strategies(reg)  # second call must not raise
    catalog = reg.list_available()
    assert sum(1 for c in catalog if c["name"] == "copy_trade") == 1


# ---------------------------------------------------------------------------
# CopyTradeStrategy.scan
# ---------------------------------------------------------------------------


_USER_UUID = UUID("12345678-1234-5678-1234-567812345678")
_TARGET_UUID = UUID("aabbccdd-1234-5678-1234-567812345678")


def _user_ctx(available: float = 1000.0,
              capital_pct: float = 0.10) -> UserContext:
    return UserContext(
        user_id=str(_USER_UUID),
        sub_account_id="sub_1",
        risk_profile="balanced",
        capital_allocation_pct=capital_pct,
        available_balance_usdc=available,
    )


def _market_filters() -> MarketFilters:
    return MarketFilters(
        categories=["politics"],
        min_liquidity=0.0,
        max_time_to_resolution_days=30,
        blacklisted_market_ids=[],
    )


class _FakeConn:
    """Minimal asyncpg.Connection stand-in.

    Implements only the methods CopyTradeStrategy + handler reach for. Each
    instance carries a script of (sql_substring -> result) — first match wins.
    """

    def __init__(self, fetch_results: list[list[dict]] | None = None,
                 fetchrow_results: list | None = None) -> None:
        self._fetch_results = list(fetch_results or [])
        self._fetchrow_results = list(fetchrow_results or [])

    async def fetch(self, sql, *args):
        if not self._fetch_results:
            return []
        return self._fetch_results.pop(0)

    async def fetchrow(self, sql, *args):
        if not self._fetchrow_results:
            return None
        return self._fetchrow_results.pop(0)

    async def fetchval(self, sql, *args):
        return 0

    async def execute(self, sql, *args):
        return None


class _FakePool:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _Ctx:
            async def __aenter__(self_inner):
                return conn

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        return _Ctx()


def _patch_pool(conn: _FakeConn):
    """Patch every `get_pool()` site the strategy reaches for at scan/exit time."""
    pool = _FakePool(conn)
    return [
        patch(
            "projects.polymarket.crusaderbot.domain.strategy.strategies."
            "copy_trade.get_pool",
            return_value=pool,
        ),
    ]


def test_scan_returns_empty_when_no_targets():
    conn = _FakeConn(fetch_results=[[]])  # _load_active_copy_targets -> []
    strat = CopyTradeStrategy()
    with _patch_pool(conn)[0]:
        out = asyncio.run(strat.scan(_market_filters(), _user_ctx()))
    assert out == []


def test_scan_emits_signal_for_fresh_buy():
    target_row = {
        "id": _TARGET_UUID,
        "user_id": _USER_UUID,
        "target_wallet_address": "0x" + "a" * 40,
        "scale_factor": 1.0,
        "trades_mirrored": 0,
        "created_at": datetime.now(timezone.utc),
    }
    fresh_trade = {
        "transactionHash": "0x" + "1" * 64,
        "conditionId": "cond_1",
        "market": "mkt_1",
        "side": "BUY",
        "outcome": "Yes",
        "usdcSize": 100.0,
        "price": 0.50,
        "timestamp": int(datetime.now(timezone.utc).timestamp()),
    }
    conn = _FakeConn(
        fetch_results=[[target_row]],
        fetchrow_results=[None],  # _already_mirrored -> not yet
    )

    async def fake_fetch(wallet, limit=20):
        return [fresh_trade]

    strat = CopyTradeStrategy()
    with _patch_pool(conn)[0], patch(
        "projects.polymarket.crusaderbot.domain.strategy.strategies."
        "copy_trade.fetch_recent_wallet_trades",
        side_effect=fake_fetch,
    ):
        out = asyncio.run(strat.scan(_market_filters(), _user_ctx()))
    assert len(out) == 1
    sig = out[0]
    assert sig.market_id == "mkt_1"
    assert sig.condition_id == "cond_1"
    assert sig.side == "YES"
    assert sig.confidence == 0.75
    assert sig.suggested_size_usdc > 0.0
    assert sig.metadata["source_tx_hash"] == fresh_trade["transactionHash"]
    assert sig.metadata["copy_target_id"] == str(_TARGET_UUID)
    assert sig.metadata["leader_wallet"] == target_row["target_wallet_address"]


def test_already_mirrored_scopes_query_per_follower():
    """The dedup query must filter on (copy_target_id, source_tx_hash) so the
    same leader transaction can be mirrored independently by every follower."""
    from projects.polymarket.crusaderbot.domain.strategy.strategies import (
        copy_trade as ct_mod,
    )

    captured: dict = {}

    class _CapturingConn:
        async def fetchrow(self, sql, *args):
            captured["sql"] = sql
            captured["args"] = args
            return None  # not yet mirrored

    class _CapturingPool:
        def acquire(self):
            conn = _CapturingConn()

            class _Ctx:
                async def __aenter__(self_inner):
                    return conn

                async def __aexit__(self_inner, *_):
                    return False

            return _Ctx()

    with patch.object(ct_mod, "get_pool", return_value=_CapturingPool()):
        out = asyncio.run(
            ct_mod._already_mirrored(_TARGET_UUID, "0x" + "a" * 64),
        )
    assert out is False
    assert "copy_target_id = $1" in captured["sql"]
    assert "source_tx_hash = $2" in captured["sql"]
    # asyncpg coerces the UUID at the protocol layer; the strategy passes the
    # parsed UUID, not the raw string, so the queries can use the index.
    assert captured["args"][0] == _TARGET_UUID
    assert captured["args"][1] == "0x" + "a" * 64


def test_already_mirrored_returns_false_on_blank_inputs():
    from projects.polymarket.crusaderbot.domain.strategy.strategies import (
        copy_trade as ct_mod,
    )

    out = asyncio.run(ct_mod._already_mirrored(None, "0xabc"))
    assert out is False
    out = asyncio.run(ct_mod._already_mirrored(_TARGET_UUID, ""))
    assert out is False


def test_scan_dedupes_already_mirrored_trades():
    target_row = {
        "id": _TARGET_UUID,
        "user_id": _USER_UUID,
        "target_wallet_address": "0x" + "a" * 40,
        "scale_factor": 1.0,
        "trades_mirrored": 0,
        "created_at": datetime.now(timezone.utc),
    }
    seen_trade = {
        "transactionHash": "0x" + "f" * 64,
        "conditionId": "cond_seen",
        "market": "mkt_seen",
        "side": "BUY",
        "outcome": "Yes",
        "usdcSize": 100.0,
        "price": 0.50,
        "timestamp": int(datetime.now(timezone.utc).timestamp()),
    }
    conn = _FakeConn(
        fetch_results=[[target_row]],
        fetchrow_results=[{"?column?": 1}],  # _already_mirrored -> True
    )

    async def fake_fetch(wallet, limit=20):
        return [seen_trade]

    strat = CopyTradeStrategy()
    with _patch_pool(conn)[0], patch(
        "projects.polymarket.crusaderbot.domain.strategy.strategies."
        "copy_trade.fetch_recent_wallet_trades",
        side_effect=fake_fetch,
    ):
        out = asyncio.run(strat.scan(_market_filters(), _user_ctx()))
    assert out == []


def test_scan_drops_stale_trades_outside_window():
    target_row = {
        "id": _TARGET_UUID,
        "user_id": _USER_UUID,
        "target_wallet_address": "0x" + "a" * 40,
        "scale_factor": 1.0,
        "trades_mirrored": 0,
        "created_at": datetime.now(timezone.utc),
    }
    stale = {
        "transactionHash": "0x" + "2" * 64,
        "conditionId": "cond_2",
        "market": "mkt_2",
        "side": "BUY",
        "outcome": "Yes",
        "usdcSize": 100.0,
        "price": 0.50,
        # 30 minutes ago — well outside the 5-minute scan window.
        "timestamp": int(
            (datetime.now(timezone.utc) - timedelta(minutes=30)).timestamp()
        ),
    }
    conn = _FakeConn(
        fetch_results=[[target_row]],
        fetchrow_results=[None],
    )

    async def fake_fetch(wallet, limit=20):
        return [stale]

    strat = CopyTradeStrategy()
    with _patch_pool(conn)[0], patch(
        "projects.polymarket.crusaderbot.domain.strategy.strategies."
        "copy_trade.fetch_recent_wallet_trades",
        side_effect=fake_fetch,
    ):
        out = asyncio.run(strat.scan(_market_filters(), _user_ctx()))
    assert out == []


def test_scan_skips_trade_when_size_below_floor():
    """User with $5 available + 0.001 capital_alloc cannot afford a $1 trade."""
    target_row = {
        "id": _TARGET_UUID,
        "user_id": _USER_UUID,
        "target_wallet_address": "0x" + "a" * 40,
        "scale_factor": 1.0,
        "trades_mirrored": 0,
        "created_at": datetime.now(timezone.utc),
    }
    fresh = {
        "transactionHash": "0x" + "3" * 64,
        "conditionId": "cond_3",
        "market": "mkt_3",
        "side": "BUY",
        "outcome": "Yes",
        "usdcSize": 100.0,
        "price": 0.50,
        "timestamp": int(datetime.now(timezone.utc).timestamp()),
    }
    conn = _FakeConn(
        fetch_results=[[target_row]],
        fetchrow_results=[None],
    )

    async def fake_fetch(wallet, limit=20):
        return [fresh]

    strat = CopyTradeStrategy()
    with _patch_pool(conn)[0], patch(
        "projects.polymarket.crusaderbot.domain.strategy.strategies."
        "copy_trade.fetch_recent_wallet_trades",
        side_effect=fake_fetch,
    ):
        # cap = 5 * 0.001 = $0.005 which is below the $1 floor → skip.
        out = asyncio.run(
            strat.scan(_market_filters(), _user_ctx(available=5.0,
                                                    capital_pct=0.001))
        )
    assert out == []


# ---------------------------------------------------------------------------
# CopyTradeStrategy.evaluate_exit
# ---------------------------------------------------------------------------


def test_evaluate_exit_holds_when_metadata_missing():
    strat = CopyTradeStrategy()
    out = asyncio.run(strat.evaluate_exit({}))
    assert out.should_exit is False and out.reason == "hold"


def test_evaluate_exit_holds_when_leader_still_in():
    async def fake_open(wallet):
        return {"cond_x"}

    strat = CopyTradeStrategy()
    with patch(
        "projects.polymarket.crusaderbot.domain.strategy.strategies."
        "copy_trade.fetch_leader_open_condition_ids",
        side_effect=fake_open,
    ):
        out = asyncio.run(strat.evaluate_exit({
            "metadata": {
                "leader_wallet": "0xabc",
                "condition_id": "cond_x",
            },
        }))
    assert out.should_exit is False and out.reason == "hold"


def test_evaluate_exit_signals_strategy_exit_when_leader_left():
    async def fake_open(wallet):
        return set()  # leader holds nothing

    strat = CopyTradeStrategy()
    with patch(
        "projects.polymarket.crusaderbot.domain.strategy.strategies."
        "copy_trade.fetch_leader_open_condition_ids",
        side_effect=fake_open,
    ):
        out = asyncio.run(strat.evaluate_exit({
            "metadata": {
                "leader_wallet": "0xabc",
                "condition_id": "cond_x",
            },
        }))
    assert out.should_exit is True
    assert out.reason == "strategy_exit"
    assert out.metadata.get("reason") == "leader_exit"


def test_evaluate_exit_holds_when_fetch_fails():
    async def fake_open(wallet):
        raise RuntimeError("api down")

    strat = CopyTradeStrategy()
    with patch(
        "projects.polymarket.crusaderbot.domain.strategy.strategies."
        "copy_trade.fetch_leader_open_condition_ids",
        side_effect=fake_open,
    ):
        out = asyncio.run(strat.evaluate_exit({
            "metadata": {
                "leader_wallet": "0xabc",
                "condition_id": "cond_x",
            },
        }))
    assert out.should_exit is False and out.reason == "hold"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def test_normalise_side_only_accepts_buy_legs():
    assert _normalise_side({"side": "BUY", "outcome": "Yes"}) == "YES"
    assert _normalise_side({"side": "BUY", "outcome": "No"}) == "NO"
    assert _normalise_side({"side": "SELL", "outcome": "Yes"}) is None
    assert _normalise_side({"side": "BUY", "outcome": "MAYBE"}) is None


def test_parse_trade_timestamp_handles_unix_int():
    out = _parse_trade_timestamp({"timestamp": 1700000000})
    assert out is not None and out.tzinfo is not None


def test_parse_trade_timestamp_handles_iso8601_z():
    out = _parse_trade_timestamp({"timestamp": "2026-05-04T12:00:00Z"})
    assert out is not None and out.year == 2026


def test_parse_trade_timestamp_returns_none_on_garbage():
    assert _parse_trade_timestamp({"timestamp": "not-a-date"}) is None
    assert _parse_trade_timestamp({}) is None


def test_coerce_float_safe():
    assert _coerce_float(None) == 0.0
    assert _coerce_float("3.14") == pytest.approx(3.14)
    assert _coerce_float("nope") == 0.0


# ---------------------------------------------------------------------------
# Telegram handler — wallet validation + truncate
# ---------------------------------------------------------------------------


def test_normalise_wallet_accepts_canonical_form():
    addr = "0x" + "A" * 40
    out = _normalise_wallet(addr)
    assert out == addr.lower()


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "0x123",                         # too short
        "0x" + "z" * 40,                 # non-hex
        "12" + "a" * 40,                 # missing 0x
        "0x" + "a" * 41,                 # too long
        "  0x" + "a" * 40 + "  ",        # we strip whitespace, so this is fine
    ],
)
def test_normalise_wallet_rejects_invalid(bad):
    out = _normalise_wallet(bad)
    if bad.strip() == "0x" + "a" * 40:
        # whitespace-only flank is intentionally accepted via .strip()
        assert out == "0x" + "a" * 40
    else:
        assert out is None


def test_truncate_wallet_format():
    addr = "0x" + "a" * 40
    truncated = _truncate_wallet(addr)
    assert truncated.startswith("0xaaaaaa") and "…" in truncated
    assert truncated.endswith("aaaa")


def test_copy_targets_list_kb_one_button_per_target():
    addrs = [f"0x{i:040x}" for i in range(3)]
    kb = copy_targets_list_kb(addrs)
    # 3 rows, one button each.
    assert len(kb.inline_keyboard) == 3
    assert all(len(row) == 1 for row in kb.inline_keyboard)
    for row, addr in zip(kb.inline_keyboard, addrs):
        assert row[0].callback_data == f"copytrade:remove:{addr}"
