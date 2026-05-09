"""Unit tests for Phase 4C order lifecycle management.

Covers:
  * Paper mode: synthetic FILLED after 1 poll cycle (no broker call)
  * Live mode: broker FILLED -> _on_fill (DB update + fills row + notify)
  * Live mode: broker CANCELLED -> _on_cancel (status + position rollback)
  * Live mode: broker EXPIRED  -> _on_expiry (same shape as cancel)
  * Stale: max attempts reached -> operator notify + status='stale'
  * Touch: still-open broker status -> poll_attempts incremented only
  * ClobAdapter.post_order forwards tick_size + neg_risk to OrderBuilder
  * MockClobClient: cancel_all_orders / get_fills / get_open_orders reachable
  * ClobAdapter.get_fills / get_open_orders / cancel_all_orders normalise
    response shapes and round-trip the path / method we expect
  * Scheduler registers the order_lifecycle job on startup

No real DB — asyncpg.Pool and Connection are replaced with in-memory
stand-ins that capture every issued query for assertions. No real
network — ClobClientProtocol is replaced with AsyncMock + MockClobClient.
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest

from projects.polymarket.crusaderbot.domain.execution import lifecycle as lc
from projects.polymarket.crusaderbot.domain.execution.lifecycle import (
    OrderLifecycleManager,
    _aggregate_fills,
    _broker_status,
    poll_once,
)
from projects.polymarket.crusaderbot.integrations.clob import MockClobClient
from projects.polymarket.crusaderbot.integrations.clob.adapter import ClobAdapter


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fake DB
# ---------------------------------------------------------------------------


def _make_order(
    *,
    order_id: UUID | None = None,
    user_id: UUID | None = None,
    status: str = "submitted",
    polymarket_order_id: str = "broker-1",
    poll_attempts: int = 0,
    side: str = "yes",
    market_id: str = "mkt-1",
    price: float = 0.55,
    size_usdc: float = 100.0,
    fill_size: float | None = None,
    fill_price: float | None = None,
) -> dict:
    return {
        "id": order_id or uuid4(),
        "user_id": user_id or uuid4(),
        "market_id": market_id,
        "side": side,
        "size_usdc": size_usdc,
        "price": price,
        "polymarket_order_id": polymarket_order_id,
        "status": status,
        "poll_attempts": poll_attempts,
        "mode": "live",
        "fill_size": fill_size,
        "fill_price": fill_price,
    }


class FakeConn:
    def __init__(
        self, *, orders: list[dict], telegram_id: int | None = 99,
        position_rolled_back: bool = True,
    ) -> None:
        self._orders = orders
        self._telegram_id = telegram_id
        self._position_rolled_back = position_rolled_back
        self.executed: list[tuple] = []
        self.fetched: list[tuple] = []
        # state captured by the lifecycle manager via UPDATE ... RETURNING id
        self.terminal_updates: list[dict] = []
        self.position_updates: list[tuple] = []
        self.fills_inserted: list[tuple] = []
        self.touches: list[tuple] = []
        self.ledger_inserts: list[tuple] = []
        self.wallet_updates: list[tuple] = []
        self.return_terminal_id: bool = True

    async def fetch(self, query: str, *args: Any) -> list[dict]:
        self.fetched.append((query, args))
        if "FROM orders" in query and "status = ANY" in query:
            return [dict(o) for o in self._orders]
        return []

    async def fetchrow(self, query: str, *args: Any) -> dict | None:
        if "UPDATE positions" in query and "RETURNING id, user_id, size_usdc" in query:
            self.position_updates.append((query, args))
            if not self._position_rolled_back:
                return None
            order_id = args[0]
            order = next(
                (o for o in self._orders if o["id"] == order_id),
                self._orders[0] if self._orders else None,
            )
            if order is None:
                return None
            return {
                "id": uuid4(),
                "user_id": order["user_id"],
                "size_usdc": order["size_usdc"],
            }
        return None

    async def fetchval(self, query: str, *args: Any) -> Any:
        if "FROM users WHERE id" in query:
            return self._telegram_id
        if "RETURNING id" in query:
            if not self.return_terminal_id:
                return None
            self.terminal_updates.append({"query": query, "args": args})
            return args[0]
        return None

    async def execute(self, query: str, *args: Any) -> str:
        self.executed.append((query, args))
        if "INSERT INTO fills" in query:
            self.fills_inserted.append(args)
        elif "INSERT INTO ledger" in query:
            self.ledger_inserts.append(args)
        elif "UPDATE wallets" in query:
            self.wallet_updates.append(args)
        elif "UPDATE positions" in query:
            self.position_updates.append((query, args))
        elif "UPDATE orders\n                   SET poll_attempts" in query:
            self.touches.append(args)
        return "OK"

    def transaction(self) -> "_FakeTx":
        return _FakeTx()


class _FakeTx:
    async def __aenter__(self) -> "_FakeTx":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False


class _FakeAcquire:
    def __init__(self, conn: FakeConn) -> None:
        self._conn = conn

    async def __aenter__(self) -> FakeConn:
        return self._conn

    async def __aexit__(self, *exc: Any) -> bool:
        return False


class FakePool:
    def __init__(self, conn: FakeConn) -> None:
        self._conn = conn

    def acquire(self) -> _FakeAcquire:
        return _FakeAcquire(self._conn)


class FakeSettings:
    def __init__(self, *, use_real_clob: bool, max_attempts: int = 48) -> None:
        self.USE_REAL_CLOB = use_real_clob
        self.ORDER_POLL_MAX_ATTEMPTS = max_attempts


def _build_manager(
    *,
    conn: FakeConn,
    settings: FakeSettings,
    clob_factory=None,
) -> tuple[OrderLifecycleManager, AsyncMock, AsyncMock, AsyncMock]:
    notify_user = AsyncMock(return_value=True)
    notify_operator = AsyncMock(return_value=None)
    audit_write = AsyncMock(return_value=None)
    mgr = OrderLifecycleManager(
        settings=settings,
        pool=FakePool(conn),
        clob_factory=clob_factory,
        notify_user=notify_user,
        notify_operator=notify_operator,
        audit_write=audit_write,
    )
    return mgr, notify_user, notify_operator, audit_write


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------


def test_broker_status_normalises_filled_aliases():
    assert _broker_status({"status": "MATCHED"}) == "filled"
    assert _broker_status({"status": "filled"}) == "filled"
    assert _broker_status({"state": "complete"}) == "filled"


def test_broker_status_normalises_cancelled_and_expired():
    assert _broker_status({"status": "Cancelled"}) == "cancelled"
    assert _broker_status({"status": "canceled"}) == "cancelled"
    assert _broker_status({"orderStatus": "expired"}) == "expired"


def test_broker_status_unknown_falls_back_to_open():
    assert _broker_status({}) == "open"
    assert _broker_status({"status": "resting"}) == "open"


def test_broker_status_strips_order_status_prefix():
    """Real CLOB responses use enum-style strings (ORDER_STATUS_MATCHED).
    Without prefix-stripping these fall through to 'open' and live orders
    silently stall — covered by Codex P1 review on PR #913.
    """
    assert _broker_status({"status": "ORDER_STATUS_MATCHED"}) == "filled"
    assert _broker_status({"status": "order_status_canceled"}) == "cancelled"
    assert _broker_status({"orderStatus": "ORDER_STATUS_EXPIRED"}) == "expired"


def test_broker_status_market_resolved_cancel_routes_to_cancelled():
    """Codex P1: ``ORDER_STATUS_CANCELED_MARKET_RESOLVED`` is a real
    Polymarket terminal status. Without prefix-matching it would fall
    through to 'open' and never close the position / refund USDC.
    """
    assert _broker_status({
        "status": "ORDER_STATUS_CANCELED_MARKET_RESOLVED"
    }) == "cancelled"
    assert _broker_status({"status": "canceled_market_resolved"}) == "cancelled"


def test_aggregate_fills_weighted_average():
    fills = [
        {"price": "0.50", "size": "10"},
        {"price": "0.60", "size": "20"},
    ]
    avg, total = _aggregate_fills(fills, fallback={})
    # weighted: (0.5*10 + 0.6*20)/30 = 17/30
    assert total == pytest.approx(30.0)
    assert avg == pytest.approx(17 / 30, rel=1e-6)


def test_aggregate_fills_empty_uses_fallback_price_and_size():
    avg, total = _aggregate_fills(
        [], fallback={"price": 0.4, "size_usdc": 100},
    )
    assert avg == pytest.approx(0.4)
    assert total == pytest.approx(250.0)


# ---------------------------------------------------------------------------
# poll_once: paper mode
# ---------------------------------------------------------------------------


async def test_paper_mode_never_synthesises_fill_for_live_rows():
    """Codex P1 review: USE_REAL_CLOB=False MUST NOT synthesise a fill
    on mode='live' orders. Real live orders are only created when
    USE_REAL_CLOB was True; if an operator later disables the toggle
    while orders remain open at the broker, falsely 'filling' them
    in DB without broker confirmation would corrupt positions / fills /
    wallets. The manager just touches the row instead.
    """
    order = _make_order()
    conn = FakeConn(orders=[order])
    settings = FakeSettings(use_real_clob=False)
    mgr, notify_user, _notify_op, audit_write = _build_manager(
        conn=conn, settings=settings,
    )

    out = await mgr.poll_once()

    assert out["open"] == 1
    assert out["filled"] == 0
    notify_user.assert_not_awaited()
    audit_write.assert_not_awaited()
    assert conn.fills_inserted == []
    # poll_attempts++ via a touch.
    assert len(conn.touches) == 1


async def test_paper_mode_does_not_call_broker():
    order = _make_order()
    conn = FakeConn(orders=[order])
    settings = FakeSettings(use_real_clob=False)
    factory_called = []

    def factory(_s):
        factory_called.append(_s)
        raise AssertionError("clob_factory must not be called in paper mode")

    mgr, *_ = _build_manager(
        conn=conn, settings=settings, clob_factory=factory,
    )
    await mgr.poll_once()
    assert factory_called == []


# ---------------------------------------------------------------------------
# poll_once: live mode dispatch
# ---------------------------------------------------------------------------


async def test_live_filled_writes_fills_and_notifies():
    order = _make_order(polymarket_order_id="brk-fill-1", price=0.55,
                        size_usdc=82.5)
    conn = FakeConn(orders=[order])
    settings = FakeSettings(use_real_clob=True)

    client = AsyncMock()
    # The lifecycle now derives the fill aggregate from the broker
    # order detail's size_matched + price fields rather than a separate
    # /data/trades query (Codex P1 — taker_order_id filter is unsupported).
    # ``size_matched`` is Polymarket fixed-math with 6 decimals, so 150
    # shares is reported as 150_000_000 (Codex P1 follow-up).
    client.get_order = AsyncMock(return_value={
        "status": "matched", "size_matched": 150_000_000, "price": 0.55,
    })
    client.aclose = AsyncMock(return_value=None)

    mgr, notify_user, _no, audit_write = _build_manager(
        conn=conn, settings=settings, clob_factory=lambda _s: client,
    )
    out = await mgr.poll_once()

    assert out["filled"] == 1
    client.get_order.assert_awaited_with("brk-fill-1")
    # One synthetic aggregate fill row inserted.
    assert len(conn.fills_inserted) == 1
    # User got the fill alert.
    notify_user.assert_awaited()
    # Audit recorded action='order_filled'.
    actions = [c.kwargs["action"] for c in audit_write.await_args_list]
    assert "order_filled" in actions


async def test_live_cancelled_rolls_position_back():
    order = _make_order()
    conn = FakeConn(orders=[order])
    settings = FakeSettings(use_real_clob=True)

    client = AsyncMock()
    client.get_order = AsyncMock(return_value={
        "status": "cancelled", "size_matched": 0,
    })
    client.aclose = AsyncMock(return_value=None)

    mgr, notify_user, _no, audit_write = _build_manager(
        conn=conn, settings=settings, clob_factory=lambda _s: client,
    )
    out = await mgr.poll_once()

    assert out["cancelled"] == 1
    actions = [c.kwargs["action"] for c in audit_write.await_args_list]
    assert "order_cancelled" in actions
    # An UPDATE positions ... status='cancelled' was issued.
    assert any(
        "UPDATE positions" in q and "status = 'cancelled'" in q
        for q, _ in conn.position_updates
    )
    notify_user.assert_awaited()


async def test_live_cancelled_credits_full_refund_when_no_fills():
    """Codex P1 review: a cancelled live order with no fills must credit
    the full size_usdc back to the user's wallet. The execute() path
    debits the full size at position-insert time; without this refund
    the user's balance silently locks the cancelled notional.
    """
    order = _make_order(size_usdc=100.0)
    conn = FakeConn(orders=[order])
    settings = FakeSettings(use_real_clob=True)

    client = AsyncMock()
    client.get_order = AsyncMock(return_value={
        "status": "cancelled", "size_matched": 0,
    })
    client.aclose = AsyncMock(return_value=None)

    mgr, *_ = _build_manager(
        conn=conn, settings=settings, clob_factory=lambda _s: client,
    )
    await mgr.poll_once()

    assert len(conn.ledger_inserts) == 1
    user_id, type_, amount, _ref, _note = conn.ledger_inserts[0]
    from decimal import Decimal as _D
    assert type_ == "adjustment"
    assert _D(str(amount)) == _D("100")
    # Wallet UPDATE applied alongside the ledger insert.
    assert len(conn.wallet_updates) == 1


async def test_live_cancelled_partial_fill_resizes_position_and_refunds_remainder():
    """Codex P1 follow-up: GTC partial-fill-then-cancel must reconcile
    broker fills before refunding. Without it the user keeps matched
    shares AND receives a full USDC refund — duplicate exposure.

    Broker reports size_matched=50 at price=0.40 -> $20 matched;
    size_usdc=100 -> $80 refund. Position resizes to size_usdc=20 and
    stays 'open' so the user retains the matched share position; a
    synthetic fill row is recorded.
    """
    order = _make_order(size_usdc=100.0)
    conn = FakeConn(orders=[order])
    settings = FakeSettings(use_real_clob=True)

    client = AsyncMock()
    # Fixed-math: 50 shares == 50_000_000 in the broker payload.
    client.get_order = AsyncMock(return_value={
        "status": "cancelled", "size_matched": 50_000_000, "price": 0.40,
    })
    client.aclose = AsyncMock(return_value=None)

    mgr, *_ = _build_manager(
        conn=conn, settings=settings, clob_factory=lambda _s: client,
    )
    await mgr.poll_once()

    # Refund credit = $80 unfilled.
    from decimal import Decimal as _D
    assert len(conn.ledger_inserts) == 1
    _user, type_, amount, *_ = conn.ledger_inserts[0]
    assert type_ == "adjustment"
    assert _D(str(amount)) == _D("80.0000")
    # Position UPDATE went through the RESIZE branch (no
    # status='cancelled', has SET size_usdc + entry_price).
    resize_qs = [
        q for q, _a in conn.position_updates
        if "SET size_usdc" in q and "entry_price" in q
    ]
    assert resize_qs, conn.position_updates
    cancel_qs = [
        q for q, _a in conn.position_updates
        if "status = 'cancelled'" in q
    ]
    assert not cancel_qs, "partial fill should NOT roll position to cancelled"
    # Per-fill row written for the matched portion.
    assert len(conn.fills_inserted) == 1


async def test_live_cancelled_skips_credit_when_no_position_rolled_back():
    """If the position UPDATE returned no row (order was 'pending' and
    never reached the position insert) no ledger debit ever happened —
    so no refund is owed.
    """
    order = _make_order()
    conn = FakeConn(orders=[order], position_rolled_back=False)
    settings = FakeSettings(use_real_clob=True)

    client = AsyncMock()
    client.get_order = AsyncMock(return_value={
        "status": "cancelled", "size_matched": 0,
    })
    client.aclose = AsyncMock(return_value=None)

    mgr, *_ = _build_manager(
        conn=conn, settings=settings, clob_factory=lambda _s: client,
    )
    await mgr.poll_once()

    assert conn.ledger_inserts == []
    assert conn.wallet_updates == []


async def test_live_expired_credits_refund_same_as_cancel():
    order = _make_order(size_usdc=50.0)
    conn = FakeConn(orders=[order])
    settings = FakeSettings(use_real_clob=True)

    client = AsyncMock()
    client.get_order = AsyncMock(return_value={
        "status": "expired", "size_matched": 0,
    })
    client.aclose = AsyncMock(return_value=None)

    mgr, *_ = _build_manager(
        conn=conn, settings=settings, clob_factory=lambda _s: client,
    )
    await mgr.poll_once()

    assert len(conn.ledger_inserts) == 1
    from decimal import Decimal as _D
    _, type_, amount, *_ = conn.ledger_inserts[0]
    assert type_ == "adjustment"
    assert _D(str(amount)) == _D("50")


async def test_live_expired_uses_expiry_path():
    order = _make_order()
    conn = FakeConn(orders=[order])
    settings = FakeSettings(use_real_clob=True)

    client = AsyncMock()
    client.get_order = AsyncMock(return_value={
        "status": "expired", "size_matched": 0,
    })
    client.aclose = AsyncMock(return_value=None)

    mgr, _nu, _no, audit_write = _build_manager(
        conn=conn, settings=settings, clob_factory=lambda _s: client,
    )
    out = await mgr.poll_once()

    assert out["expired"] == 1
    actions = [c.kwargs["action"] for c in audit_write.await_args_list]
    assert "order_expired" in actions


async def test_live_open_status_only_touches_poll_attempts():
    order = _make_order(poll_attempts=3)
    conn = FakeConn(orders=[order])
    settings = FakeSettings(use_real_clob=True)

    client = AsyncMock()
    client.get_order = AsyncMock(return_value={"status": "resting"})
    client.aclose = AsyncMock(return_value=None)

    mgr, notify_user, _no, audit_write = _build_manager(
        conn=conn, settings=settings, clob_factory=lambda _s: client,
    )
    out = await mgr.poll_once()

    assert out["open"] == 1
    # No terminal action audited.
    actions = [c.kwargs["action"] for c in audit_write.await_args_list]
    assert "order_filled" not in actions
    assert "order_cancelled" not in actions
    # Telegram user notification not sent for still-open orders.
    notify_user.assert_not_awaited()
    # Touch UPDATE recorded.
    assert len(conn.touches) == 1


async def test_stale_after_max_attempts_pages_operator():
    order = _make_order(poll_attempts=47)
    conn = FakeConn(orders=[order])
    settings = FakeSettings(use_real_clob=True, max_attempts=48)

    client = AsyncMock()
    client.get_order = AsyncMock(return_value={"status": "resting"})
    client.aclose = AsyncMock(return_value=None)

    mgr, _nu, notify_operator, audit_write = _build_manager(
        conn=conn, settings=settings, clob_factory=lambda _s: client,
    )
    out = await mgr.poll_once()

    assert out["stale"] == 1
    notify_operator.assert_awaited()
    assert "STALE ORDER" in notify_operator.call_args.args[0]
    actions = [c.kwargs["action"] for c in audit_write.await_args_list]
    assert "order_stale" in actions


async def test_clob_factory_failure_aborts_sweep():
    order = _make_order()
    conn = FakeConn(orders=[order])
    settings = FakeSettings(use_real_clob=True)

    from projects.polymarket.crusaderbot.integrations.clob import (
        ClobConfigError,
    )

    def factory(_s):
        raise ClobConfigError("missing creds")

    mgr, *_ = _build_manager(
        conn=conn, settings=settings, clob_factory=factory,
    )
    out = await mgr.poll_once()

    assert out["errors"] == 1
    assert out["polled"] == 0  # the sweep never iterates rows


async def test_terminal_race_skips_when_already_terminal():
    order = _make_order()
    conn = FakeConn(orders=[order])
    conn.return_terminal_id = False  # UPDATE ... RETURNING id returns NULL
    settings = FakeSettings(use_real_clob=True)

    client = AsyncMock()
    client.get_order = AsyncMock(return_value={
        "status": "matched", "size_matched": 100_000_000, "price": 0.55,
    })
    client.aclose = AsyncMock(return_value=None)

    mgr, notify_user, _no, audit_write = _build_manager(
        conn=conn, settings=settings, clob_factory=lambda _s: client,
    )
    out = await mgr.poll_once()

    # Bucketed as filled because get_order said "matched", but the
    # transactional UPDATE skipped, so no fills row + no audit + no
    # user notify.
    assert out["filled"] == 1
    assert conn.fills_inserted == []
    notify_user.assert_not_awaited()


async def test_live_cancelled_market_resolved_routes_to_cancel_path():
    """Codex P1: ``ORDER_STATUS_CANCELED_MARKET_RESOLVED`` (a real
    Polymarket terminal status when the underlying market resolves
    while the order is still resting) must be treated as a cancel —
    refund unfilled USDC, mark order terminal, roll the position back.
    Before the prefix-match fix, this fell through to 'open' and
    eventually became stale.
    """
    order = _make_order(size_usdc=100.0)
    conn = FakeConn(orders=[order])
    settings = FakeSettings(use_real_clob=True)

    client = AsyncMock()
    client.get_order = AsyncMock(return_value={
        "status": "ORDER_STATUS_CANCELED_MARKET_RESOLVED",
        "size_matched": 0,
    })
    client.aclose = AsyncMock(return_value=None)

    mgr, *_ = _build_manager(
        conn=conn, settings=settings, clob_factory=lambda _s: client,
    )
    out = await mgr.poll_once()

    assert out["cancelled"] == 1
    # Full refund applied (no fills).
    from decimal import Decimal as _D
    assert len(conn.ledger_inserts) == 1
    _user, type_, amount, *_ = conn.ledger_inserts[0]
    assert type_ == "adjustment"
    assert _D(str(amount)) == _D("100")


async def test_broker_size_matched_fixed_math_conversion():
    """Codex P1: Polymarket's size_matched is fixed-math 1e6. A 125-share
    partial fill arrives as 125_000_000; without scaling the lifecycle
    would clamp to size_usdc and refund $0 even on partial fills.

    Order size_usdc=$100 at price=$0.40 => 250 shares would be a full fill.
    Broker reports size_matched=125_000_000 (=125 shares) at price=0.40
    => filled_notional=$50, refund=$50.
    """
    order = _make_order(size_usdc=100.0, price=0.40)
    conn = FakeConn(orders=[order])
    settings = FakeSettings(use_real_clob=True)

    client = AsyncMock()
    client.get_order = AsyncMock(return_value={
        "status": "cancelled",
        "size_matched": 125_000_000,
        "price": 0.40,
    })
    client.aclose = AsyncMock(return_value=None)

    mgr, *_ = _build_manager(
        conn=conn, settings=settings, clob_factory=lambda _s: client,
    )
    await mgr.poll_once()

    from decimal import Decimal as _D
    assert len(conn.ledger_inserts) == 1
    _user, type_, amount, *_ = conn.ledger_inserts[0]
    assert type_ == "adjustment"
    # $100 - (125 * 0.40) = $100 - $50 = $50 refund.
    assert _D(str(amount)) == _D("50.0000")


async def test_module_level_poll_once_uses_default_manager(monkeypatch):
    sentinel = AsyncMock(return_value={"polled": 0})
    monkeypatch.setattr(
        lc, "_default_manager",
        type("M", (), {"poll_once": sentinel})(),
    )
    out = await poll_once()
    sentinel.assert_awaited()
    assert out == {"polled": 0}


# ---------------------------------------------------------------------------
# MockClobClient new surface
# ---------------------------------------------------------------------------


async def test_mock_post_order_records_tick_size_and_neg_risk():
    mock = MockClobClient()
    rec = await mock.post_order(
        token_id="tok-1", side="BUY", price=0.5, size=10,
        tick_size="0.01", neg_risk=True,
    )
    assert rec["tickSize"] == "0.01"
    assert rec["negRisk"] is True


async def test_mock_cancel_all_orders_global_and_market_scoped():
    mock = MockClobClient()
    a = await mock.post_order(token_id="A", side="BUY", price=0.5, size=1)
    b = await mock.post_order(token_id="B", side="BUY", price=0.5, size=1)
    # market-scoped cancel: tokenID matches "A"
    res = await mock.cancel_all_orders(market="A")
    assert res["canceled"] == [a["orderID"]]
    # b is still resting
    open_orders = await mock.get_open_orders()
    assert [o["orderID"] for o in open_orders] == [b["orderID"]]
    # global cancel drops everything
    res2 = await mock.cancel_all_orders()
    assert res2["canceled"] == [b["orderID"]]


async def test_mock_get_fills_returns_recorded_fills():
    mock = MockClobClient()
    rec = await mock.post_order(token_id="A", side="BUY", price=0.5, size=1)
    assert await mock.get_fills(rec["orderID"]) == []
    mock.record_fill(rec["orderID"], {"fill_id": "f1", "price": 0.5, "size": 1})
    fills = await mock.get_fills(rec["orderID"])
    assert len(fills) == 1 and fills[0]["fill_id"] == "f1"


# ---------------------------------------------------------------------------
# ClobAdapter forwarding (tick_size + neg_risk)
# ---------------------------------------------------------------------------


def _build_adapter(monkeypatch, captured: dict, handler):
    """Build an adapter with on-chain signing stubbed and transport mocked.

    ``captured`` is mutated by the stub so tests can assert on the
    kwargs threaded into _build_signed_order.
    """
    import base64
    from projects.polymarket.crusaderbot.integrations.clob.adapter import (
        ClobAdapter as _ClobAdapter,
    )

    def _stub(self, **kwargs):
        captured.update(kwargs)
        return {"signature": "0xstub", "salt": "0", "maker": self._funder}

    monkeypatch.setattr(_ClobAdapter, "_build_signed_order", _stub)
    pk = "0x" + ("aa" * 32)
    secret = base64.urlsafe_b64encode(b"test-secret-32-bytes-for-hmac-aa").decode()
    return _ClobAdapter(
        api_key="api-k", api_secret=secret, passphrase="pp",
        private_key=pk, transport=httpx.MockTransport(handler),
    )


async def test_adapter_post_order_threads_tick_size_and_neg_risk(monkeypatch):
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"orderID": "BRK", "status": "matched"})

    adapter = _build_adapter(monkeypatch, captured, handler)
    try:
        await adapter.post_order(
            token_id="tok", side="BUY", price=0.55, size=10,
            tick_size="0.01", neg_risk=True,
        )
    finally:
        await adapter.aclose()

    assert captured["token_id"] == "tok"
    assert captured["tick_size"] == "0.01"
    assert captured["neg_risk"] is True


async def test_adapter_post_order_default_omits_tick_size(monkeypatch):
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"orderID": "BRK", "status": "matched"})

    adapter = _build_adapter(monkeypatch, captured, handler)
    try:
        await adapter.post_order(
            token_id="tok", side="BUY", price=0.55, size=10,
        )
    finally:
        await adapter.aclose()

    assert captured["tick_size"] is None
    assert captured["neg_risk"] is None


# ---------------------------------------------------------------------------
# ClobAdapter new lifecycle methods
# ---------------------------------------------------------------------------


async def test_adapter_get_fills_uses_supported_filters_and_client_filters(
    monkeypatch,
):
    """Codex P1: ``/data/trades`` does not accept ``taker_order_id``.
    The adapter must query by supported filters (``maker_address`` +
    optional ``market``) and select trades client-side by matching
    the order id against ``taker_order_id`` / ``maker_order_id`` /
    ``orderID`` / ``order_id`` fields.
    """
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(
            200,
            json={"data": [
                {"fill_id": "f1", "price": "0.5", "size": "10",
                 "taker_order_id": "BRK-1"},
                {"fill_id": "f2", "price": "0.4", "size": "5",
                 "taker_order_id": "OTHER"},  # must be filtered out
            ]},
        )

    adapter = _build_adapter(monkeypatch, {}, handler)
    try:
        fills = await adapter.get_fills("BRK-1", market="cond-1")
    finally:
        await adapter.aclose()

    # Exactly one matching trade returned (the OTHER trade is dropped).
    assert isinstance(fills, list) and len(fills) == 1
    assert fills[0]["fill_id"] == "f1"
    # Wire path uses supported filters only, NOT taker_order_id.
    url = str(seen[0].url)
    assert seen[0].method == "GET"
    assert "/data/trades" in url
    assert "maker_address=" in url
    assert "market=cond-1" in url
    assert "taker_order_id" not in url


async def test_adapter_get_open_orders_with_market_filter(monkeypatch):
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=[{"orderID": "O1"}])

    adapter = _build_adapter(monkeypatch, {}, handler)
    try:
        orders = await adapter.get_open_orders(market="cond-1")
    finally:
        await adapter.aclose()

    assert orders == [{"orderID": "O1"}]
    assert "market=cond-1" in str(seen[0].url)


async def test_adapter_cancel_all_orders_routes_global_vs_scoped(monkeypatch):
    seen: list[tuple[str, str, str]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = req.read().decode() if req.read() else ""
        seen.append((req.method, str(req.url.path), body))
        return httpx.Response(200, json={"canceled": []})

    adapter = _build_adapter(monkeypatch, {}, handler)
    try:
        await adapter.cancel_all_orders()
        await adapter.cancel_all_orders(market="cond-1")
    finally:
        await adapter.aclose()

    assert seen[0][1] == "/cancel-all"
    assert seen[1][1] == "/cancel-market-orders"
    assert "cond-1" in seen[1][2]


# ---------------------------------------------------------------------------
# Scheduler registration
# ---------------------------------------------------------------------------


def test_scheduler_registers_order_lifecycle_job(monkeypatch):
    """The setup_scheduler() factory must add an 'order_lifecycle' job.

    ``scheduler.py`` imports the polygon integration (web3) at module
    load; that dep is installed in CI but not in every local env, so we
    skip rather than fail when web3 is unavailable.
    """
    pytest.importorskip("web3")
    from projects.polymarket.crusaderbot import scheduler as scheduler_mod

    captured: list[dict] = []

    class FakeSched:
        def __init__(self, *args, **kwargs):
            pass

        def add_job(self, func, *args, **kwargs):
            captured.append({"func": func, "id": kwargs.get("id"),
                             "seconds": kwargs.get("seconds")})

        def add_listener(self, *args, **kwargs):
            pass

    monkeypatch.setattr(scheduler_mod, "AsyncIOScheduler", FakeSched)

    class _S:
        TIMEZONE = "Asia/Jakarta"
        MARKET_SCAN_INTERVAL = 300
        DEPOSIT_WATCH_INTERVAL = 120
        SIGNAL_SCAN_INTERVAL = 180
        EXIT_WATCH_INTERVAL = 60
        REDEEM_INTERVAL = 3600
        RESOLUTION_CHECK_INTERVAL = 300
        ORDER_POLL_INTERVAL_SECONDS = 30
        WS_WATCHDOG_INTERVAL_SECONDS = 60

    monkeypatch.setattr(scheduler_mod, "get_settings", lambda: _S())

    scheduler_mod.setup_scheduler()

    job_ids = [c["id"] for c in captured]
    assert "order_lifecycle" in job_ids
    job = next(c for c in captured if c["id"] == "order_lifecycle")
    assert job["seconds"] == 30
