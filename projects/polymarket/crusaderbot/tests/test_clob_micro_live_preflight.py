"""Issue-#1817 preflight matrix for the CLOB live open-order path (R00T).

The recent #1814 go-live-readiness audit and the R00T verification under #1817
both confirm the bot already has a docs-aligned, minimal CLOB live open-order
path with every preflight blocker fail-closed. This test file is the SINGLE
explicit issue-#1817-aligned matrix that pins each blocker the issue lists, so
WARP🔹CMD can read off one table and audit the safety chain end-to-end.

It deliberately does NOT duplicate the granular tests in
``test_live_execution_rewire.py`` etc. — it asserts the *integrated* fail-closed
shape of each blocker in the issue's preflight list. Every test patches the DB
pool, market-data client, audit, and notifications; **no test makes a real CLOB
call** (proven by both the source pin and the explicit-mock invariant tests at
the bottom of the file).

Mapping each test below to a Polymarket CLOB doc URL the issue cites lives in
``reports/forge/clob-micro-live-open-order-path.md`` §3.
"""
from __future__ import annotations

import asyncio
import pathlib
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from projects.polymarket.crusaderbot.domain.execution.live import (
    LivePreSubmitError,
    assert_live_guards,
    execute,
)
from projects.polymarket.crusaderbot.integrations.clob import (
    ClobAuthError,
    MockClobClient,
)
from projects.polymarket.crusaderbot.wallet.ledger import live_ledger_filter_sql

_ROOT = pathlib.Path(__file__).resolve().parent.parent

ORDER_ID = UUID("11111111-1111-1111-1111-111111111111")
POSITION_ID = UUID("22222222-2222-2222-2222-222222222222")
USER_ID = uuid4()


# ---------------------------------------------------------------------------
# Fake DB + settings harness (mirrors test_live_execution_rewire.FakeConn).
# ---------------------------------------------------------------------------

class _Tx:
    async def __aenter__(self): return self
    async def __aexit__(self, *exc): return False


class FakeConn:
    def __init__(self) -> None:
        self.executed: list[tuple] = []

    async def fetchrow(self, query: str, *args: Any):
        if "INSERT INTO orders" in query:
            return {"id": ORDER_ID}
        if "INSERT INTO positions" in query:
            return {"id": POSITION_ID}
        return None

    async def fetchval(self, query: str, *args: Any):
        if "SELECT id FROM orders WHERE idempotency_key" in query:
            return None
        return None

    async def execute(self, query: str, *args: Any) -> str:
        self.executed.append((query, args))
        return "OK"

    def transaction(self) -> _Tx:
        return _Tx()


class _Acq:
    def __init__(self, conn: FakeConn): self._c = conn
    async def __aenter__(self): return self._c
    async def __aexit__(self, *exc): return False


class FakePool:
    def __init__(self, conn: FakeConn): self._c = conn
    def acquire(self) -> _Acq: return _Acq(self._c)


def _settings(**over: bool) -> Any:
    base = dict(
        ENABLE_LIVE_TRADING=True, EXECUTION_PATH_VALIDATED=True,
        CAPITAL_MODE_CONFIRMED=True, RISK_CONTROLS_VALIDATED=True,
        SECURITY_HARDENING_VALIDATED=True, USE_REAL_CLOB=True,
        USE_PER_USER_EXECUTION=False,
    )
    base.update(over)

    class _S: pass
    s = _S()
    for k, v in base.items():
        setattr(s, k, v)
    return s


def _mdc_mock(*, tick_size: str = "0.01", neg_risk: bool = False,
              tick_raises: Exception | None = None) -> Any:
    mdc = MagicMock()
    if tick_raises is not None:
        mdc.get_tick_size = AsyncMock(side_effect=tick_raises)
    else:
        mdc.get_tick_size = AsyncMock(return_value=tick_size)
    mdc.get_neg_risk = AsyncMock(return_value=neg_risk)
    mdc.__aenter__ = AsyncMock(return_value=mdc)
    mdc.__aexit__ = AsyncMock(return_value=False)
    return mdc


_EXEC = dict(
    user_id=USER_ID, telegram_user_id=12345,
    role="admin", trading_mode="live",
    market_id="mkt-abc", market_question="Will BTC be up at 17:30?",
    yes_token_id="tok-yes", no_token_id="tok-no",
    side="yes", size_usdc=Decimal("100"), price=0.6,
    idempotency_key="key-abc", strategy_type="late_entry_v3",
    tp_pct=None, sl_pct=None,
)


def _run(*, conn: FakeConn, settings: Any, client: Any, mdc: Any | None = None,
         **over: Any) -> dict:
    pool = FakePool(conn)
    with (
        patch("projects.polymarket.crusaderbot.domain.execution.live.get_settings",
              return_value=settings),
        patch("projects.polymarket.crusaderbot.domain.execution.live.get_pool",
              return_value=pool),
        patch("projects.polymarket.crusaderbot.domain.execution.live.MarketDataClient",
              return_value=(mdc or _mdc_mock())),
        patch("projects.polymarket.crusaderbot.domain.execution.live.audit.write",
              new=AsyncMock()),
        patch("projects.polymarket.crusaderbot.domain.execution.live.notifications.send",
              new=AsyncMock()),
        patch("projects.polymarket.crusaderbot.domain.execution.live.ledger.debit_in_conn",
              new=AsyncMock()),
        patch("projects.polymarket.crusaderbot.domain.execution.live._notifier.notify_entry",
              new=AsyncMock()),
    ):
        kwargs = {**_EXEC, "clob_client": client, **over}
        return asyncio.run(execute(**kwargs))


# ===========================================================================
# Preflight matrix — one test per blocker the issue lists.
# ===========================================================================

# ---- Six env guards + admin + live mode (assert_live_guards) ---------------

@pytest.mark.parametrize("flag,match", [
    ("ENABLE_LIVE_TRADING",          "ENABLE_LIVE_TRADING"),
    ("EXECUTION_PATH_VALIDATED",     "EXECUTION_PATH_VALIDATED"),
    ("CAPITAL_MODE_CONFIRMED",       "CAPITAL_MODE_CONFIRMED"),
    ("RISK_CONTROLS_VALIDATED",      "RISK_CONTROLS_VALIDATED"),
    ("SECURITY_HARDENING_VALIDATED", "SECURITY_HARDENING_VALIDATED"),
    ("USE_REAL_CLOB",                "USE_REAL_CLOB must be True"),
])
def test_preflight_each_env_guard_fails_closed(flag: str, match: str) -> None:
    s = _settings(**{flag: False})
    with (
        patch("projects.polymarket.crusaderbot.domain.execution.live.get_settings",
              return_value=s),
        pytest.raises(LivePreSubmitError, match=match),
    ):
        assert_live_guards(role="admin", trading_mode="live")


def test_preflight_role_must_be_admin() -> None:
    s = _settings()
    with (
        patch("projects.polymarket.crusaderbot.domain.execution.live.get_settings",
              return_value=s),
        pytest.raises(LivePreSubmitError, match="not admin"),
    ):
        assert_live_guards(role="user", trading_mode="live")


def test_preflight_user_must_be_in_live_mode() -> None:
    s = _settings()
    with (
        patch("projects.polymarket.crusaderbot.domain.execution.live.get_settings",
              return_value=s),
        pytest.raises(LivePreSubmitError, match="trading_mode=paper"),
    ):
        assert_live_guards(role="admin", trading_mode="paper")


# ---- CLOB credential / dry-run proof ---------------------------------------

def test_preflight_dry_run_when_use_real_clob_but_live_trading_off() -> None:
    """Issue: 'CLOB credentials present and dry-run credential proof passes'.

    The dry-run intercept is the operator's credential-proof path: it signs
    nothing, writes nothing to the DB, makes no broker call, and returns the
    explicit ``dry_run`` status so an operator can prove credentials BEFORE
    flipping ``ENABLE_LIVE_TRADING``.
    """
    s = _settings(ENABLE_LIVE_TRADING=False)
    client = MockClobClient()
    conn = FakeConn()
    result = _run(conn=conn, settings=s, client=client)
    assert result == {"status": "dry_run", "mode": "paper", "_mock": True}
    # No DB write — the precheck SELECT and dry-run return BEFORE the INSERT.
    assert all("INSERT INTO orders" not in q for q, _ in conn.executed)


def test_preflight_clob_auth_error_classified_pre_submit() -> None:
    """A signing/auth failure (bad creds) is pre-submit -> safe to paper-fall back.

    The router classifies LivePreSubmitError as the 'definitively no broker
    call happened' path, which is the docs-aligned semantic: auth fails before
    the POST.
    """
    s = _settings()
    client = MagicMock()
    client.post_order = AsyncMock(side_effect=ClobAuthError("bad signature"))
    conn = FakeConn()
    with pytest.raises(LivePreSubmitError, match="prepare failed"):
        _run(conn=conn, settings=s, client=client)


# ---- Market metadata (tick / neg_risk) preflight ---------------------------

def test_preflight_tick_size_unavailable_fails_closed() -> None:
    """Issue: 'tick size loaded and price rounded correctly'.

    If the CLOB market data API can't return tick_size, fail closed pre-submit
    rather than guess a default that would post a wrong-tick order.
    """
    s = _settings()
    client = MagicMock()
    client.post_order = AsyncMock()
    conn = FakeConn()
    mdc = _mdc_mock(tick_raises=RuntimeError("tick API down"))
    with pytest.raises(LivePreSubmitError, match="CLOB market metadata unavailable"):
        _run(conn=conn, settings=s, client=client, mdc=mdc)
    # The broker was NEVER asked to post an order.
    client.post_order.assert_not_called()


# ---- Min order shares + slippage fence -------------------------------------

def test_preflight_below_min_order_shares_fails_closed() -> None:
    """Issue: 'min order size satisfied'. CLOB minimum is 5 shares; a smaller
    order is broker-rejected, so fail closed pre-submit.

    At price 0.50 the live path computes shares = size_usdc / limit_price. A
    size of $2 → 4 shares < LIVE_MIN_ORDER_SHARES=5 → reject.
    """
    s = _settings()
    client = MagicMock()
    client.post_order = AsyncMock()
    conn = FakeConn()
    with pytest.raises(LivePreSubmitError, match="below CLOB minimum"):
        _run(conn=conn, settings=s, client=client,
             size_usdc=Decimal("2"), price=0.50)
    client.post_order.assert_not_called()


def test_preflight_slippage_above_5pct_fails_closed() -> None:
    """Issue: 'no order spam' + the 5% slippage fence. The intended limit price
    is compared to the signal price; >5% deviation rejects pre-submit so the
    bot never crosses the spread by more than the documented bound.
    """
    s = _settings()
    client = MagicMock()
    client.post_order = AsyncMock()
    conn = FakeConn()
    # best_ask + 1 tick on a 0.01 tick = 0.71 vs signal 0.60 -> 18.3% deviation.
    with pytest.raises(LivePreSubmitError, match="SLIPPAGE_REJECTED"):
        _run(conn=conn, settings=s, client=client,
             price=0.60, best_ask=0.70, best_bid=0.69)
    client.post_order.assert_not_called()


# ---- Idempotency-on-submit -------------------------------------------------

class _DuplicateConn(FakeConn):
    async def fetchval(self, query: str, *args: Any):
        if "SELECT id FROM orders WHERE idempotency_key" in query:
            return ORDER_ID  # already exists -> early-duplicate return
        return None


def test_preflight_idempotent_replay_does_not_double_submit() -> None:
    """Issue: 'no order spam' + docs ON ``order_lifecycle``. A retry on the
    same idempotency_key returns a duplicate status BEFORE any CLOB POST.
    """
    s = _settings()
    client = MagicMock()
    client.post_order = AsyncMock()
    conn = _DuplicateConn()
    result = _run(conn=conn, settings=s, client=client)
    assert result == {"status": "duplicate", "mode": "live"}
    client.post_order.assert_not_called()


# ---- Live-balance filter excludes paper/pending/reserved/withdraw-pending ---

def test_live_ledger_filter_excludes_non_live_money() -> None:
    """Issue: 'per-user confirmed available live balance >= $5 ... no pending
    withdrawal/reserved/in-position/paper balance counted'.

    The single source of truth for "live money" is ``live_ledger_filter_sql``.
    Pin its exact predicate so a future edit can't silently broaden the bucket
    to count paper top-ups, reservations, or pending withdrawals.
    """
    sql = live_ledger_filter_sql("l")
    # In:
    assert "l.type = 'deposit'" in sql
    assert "l.ref_id IS NOT NULL" in sql
    assert "EXISTS (        SELECT 1 FROM deposits d WHERE d.id = l.ref_id)" in sql
    assert "l.type = 'withdraw'" in sql
    assert "EXISTS (        SELECT 1 FROM withdrawals w WHERE w.id = l.ref_id)" in sql
    assert "EXISTS (SELECT 1 FROM positions p              WHERE p.id = l.ref_id AND p.mode = 'live')" in sql
    # Out: no reservation / paper / pending top-up tokens may sneak in.
    forbidden = (
        "reserved_for_order",
        "withdraw_pending",
        "p.mode = 'paper'",
        "p.mode = 'paper_archived'",
    )
    for f in forbidden:
        assert f not in sql, (
            f"live ledger filter must not admit {f!r} — that would count "
            "non-spendable money toward the live $5 gate"
        )


# ---- Risk-gate Kelly cap (issue: never full Kelly) ------------------------

def test_kelly_constant_is_quarter_and_capped() -> None:
    """Issue hard constraint: 'Do not weaken Kelly cap or risk constants. Do
    not allow full Kelly.' The hard-wired risk constants module sets the cap
    at 0.25; any future tamper must trip this pin.
    """
    from projects.polymarket.crusaderbot.domain.risk import constants as K
    assert K.KELLY_FRACTION == 0.25
    # Never larger than the documented owner-approved cap.
    assert K.KELLY_FRACTION <= 0.25
    assert K.SLIPPAGE_GUARD_PCT == 0.05
    assert K.LIVE_MIN_ORDER_SHARES == 5


# ===========================================================================
# Hermeticity invariants — these tests cannot reach a real CLOB / network.
# ===========================================================================

def test_no_real_clob_call_in_this_test_module() -> None:
    """Source-pin: this whole test file never imports a non-Mock CLOB client
    and only patches inside the unit under test. No background pool, no real
    aiohttp session, no live endpoints — pinned by the absence of the
    forbidden import strings."""
    src = pathlib.Path(__file__).read_text(encoding="utf-8")
    forbidden = (
        "from projects.polymarket.crusaderbot.integrations.clob.v2_client import",
        "from projects.polymarket.crusaderbot.integrations.clob.adapter import ClobAdapter",
        "from projects.polymarket.crusaderbot.integrations.clob.rust_sidecar import",
        "import aiohttp",
    )
    body = src.split("# Hermeticity invariants", 1)[0]
    for needle in forbidden:
        assert needle not in body, (
            f"this preflight matrix must stay hermetic — found {needle!r}"
        )
    # Every execute() invocation MUST go through the ``_run`` helper (which
    # patches the pool / MDC / audit / notifier). The helper itself uses
    # ``asyncio.run(execute(**kwargs))`` (a single permitted occurrence); any
    # second occurrence outside it would be a hermeticity leak.
    assert body.count("asyncio.run(execute") == 1
    # MockClobClient is allowed because it is in-memory and explicitly a mock.
    assert "MockClobClient" in src