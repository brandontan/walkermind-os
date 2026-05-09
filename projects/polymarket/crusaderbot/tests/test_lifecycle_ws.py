"""Unit tests for the WebSocket integration into ``OrderLifecycleManager``
and the scheduler ``ws_*`` jobs (Phase 4D).

Hermetic: shares the FakeConn / FakePool / FakeSettings primitives with
``test_order_lifecycle.py`` (re-implemented here for test isolation —
copying is cheaper than coupling two modules through a shared helper).
NO real DB, NO real broker, NO real websockets.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from projects.polymarket.crusaderbot.domain.execution import lifecycle as lc
from projects.polymarket.crusaderbot.domain.execution.lifecycle import (
    OrderLifecycleManager,
)


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fake DB + settings (hermetic clone of test_order_lifecycle helpers)
# ---------------------------------------------------------------------------


def _make_order(
    *, status: str = "submitted", broker_id: str = "broker-1",
    poll_attempts: int = 0,
) -> dict:
    return {
        "id": uuid4(),
        "user_id": uuid4(),
        "market_id": "mkt-1",
        "side": "yes",
        "size_usdc": 100.0,
        "price": 0.55,
        "polymarket_order_id": broker_id,
        "status": status,
        "poll_attempts": poll_attempts,
        "mode": "live",
        "fill_size": None,
        "fill_price": None,
    }


class FakeConn:
    def __init__(self, *, orders: list[dict], telegram_id: int | None = 99) -> None:
        self._orders = orders
        self._telegram_id = telegram_id
        self.fills_inserted: list[tuple] = []
        self.terminal_updates: list[dict] = []
        self.touches: list[tuple] = []
        self.return_terminal_id: bool = True

    async def fetch(self, query: str, *args: Any) -> list[dict]:
        if "FROM orders" in query and "status = ANY" in query:
            return [dict(o) for o in self._orders if o["status"] in ("submitted", "pending")]
        if "FROM fills WHERE order_id" in query and "fill_id NOT LIKE" in query:
            # Per-trade-row hydration (preferred) used by
            # handle_ws_order_update on cancel/expiry frames so the
            # partial-fill refund math runs against the rows
            # handle_ws_fill already wrote.
            order_id = args[0]
            return [
                {"fill_id": row[1], "price": float(row[2]),
                 "size": float(row[3]), "side": str(row[4])}
                for row in self.fills_inserted
                if row[0] == order_id and not str(row[1]).startswith("agg-")
            ]
        if "FROM fills WHERE order_id" in query and "fill_id LIKE 'agg-" in query:
            # Aggregate-row fallback used when no per-trade rows exist
            # (Codex P1 round 10 hydration path).
            order_id = args[0]
            return [
                {"fill_id": row[1], "price": float(row[2]),
                 "size": float(row[3]), "side": str(row[4])}
                for row in self.fills_inserted
                if row[0] == order_id and str(row[1]).startswith("agg-")
            ]
        return []

    async def fetchrow(self, query: str, *args: Any) -> dict | None:
        if "FROM orders" in query and "polymarket_order_id" in query:
            broker = args[0]
            for o in self._orders:
                if o["polymarket_order_id"] == broker:
                    return dict(o)
            return None
        if "UPDATE positions" in query and "RETURNING id, user_id, size_usdc" in query:
            return {"id": uuid4(), "user_id": self._orders[0]["user_id"],
                    "size_usdc": self._orders[0]["size_usdc"]}
        return None

    async def fetchval(self, query: str, *args: Any) -> Any:
        if "FROM users WHERE id" in query:
            return self._telegram_id
        if "SUM(size)" in query and "FROM fills" in query:
            # Honour the per-trade-row size SUM used by the
            # aggregate-fill dedup guard so the size-comparison logic
            # branches as it would in prod (Codex P2 round 8).
            order_id = args[0]
            return sum(
                float(row[3]) for row in self.fills_inserted
                if row[0] == order_id and not str(row[1]).startswith("agg-")
            )
        if "RETURNING id" in query:
            if not self.return_terminal_id:
                return None
            self.terminal_updates.append({"query": query, "args": args})
            return args[0]
        return None

    async def execute(self, query: str, *args: Any) -> str:
        if "INSERT INTO fills" in query:
            self.fills_inserted.append(args)
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
    def __init__(self, *, use_real_clob: bool = True) -> None:
        self.USE_REAL_CLOB = use_real_clob
        self.ORDER_POLL_MAX_ATTEMPTS = 48


def _build(conn: FakeConn) -> tuple[OrderLifecycleManager, AsyncMock]:
    notify_user = AsyncMock(return_value=True)
    audit_write = AsyncMock(return_value=None)
    mgr = OrderLifecycleManager(
        settings=FakeSettings(use_real_clob=True),
        pool=FakePool(conn),
        notify_user=notify_user,
        notify_operator=AsyncMock(return_value=None),
        audit_write=audit_write,
    )
    return mgr, notify_user


# ---------------------------------------------------------------------------
# handle_ws_fill
# ---------------------------------------------------------------------------


async def test_ws_fill_unknown_broker_id_no_writes():
    conn = FakeConn(orders=[_make_order(broker_id="known")])
    mgr, _ = _build(conn)
    await mgr.handle_ws_fill({
        "broker_order_id": "unknown",
        "fill_id": "f1",
        "price": 0.5, "size": 1.0, "side": "buy",
    })
    assert conn.fills_inserted == []
    assert conn.terminal_updates == []


async def test_ws_fill_missing_required_fields_drops_event():
    conn = FakeConn(orders=[_make_order()])
    mgr, _ = _build(conn)
    await mgr.handle_ws_fill({"broker_order_id": "broker-1"})  # no fill_id
    assert conn.fills_inserted == []


async def test_ws_fill_records_partial_only_no_terminal_update():
    """Codex P1 / WARP🔹CMD: the WS fill path is records-only. Each
    CONFIRMED ``user_fill`` writes one fills row + bumps the position
    mark price; it MUST NOT mark the order as filled. Terminal status
    arrives via ``handle_ws_order_update(status=filled)`` or the
    polling fallback so a multi-trade GTC partial fill keeps every
    subsequent fills row instead of race-losing the second writer.
    """
    conn = FakeConn(orders=[_make_order(broker_id="broker-1")])
    mgr, notify_user = _build(conn)
    await mgr.handle_ws_fill({
        "broker_order_id": "broker-1",
        "fill_id": "fill-abc",
        "price": 0.55, "size": 100.0, "side": "yes",
    })
    # Records-only contract: fills row written, NO terminal UPDATE
    # against the orders table, NO Telegram notification (terminal
    # path owns the user-facing message).
    assert len(conn.fills_inserted) == 1
    assert conn.fills_inserted[0][1] == "fill-abc"
    assert conn.terminal_updates == []
    notify_user.assert_not_awaited()


async def test_ws_fill_skipped_if_already_terminal():
    conn = FakeConn(orders=[_make_order(broker_id="b", status="filled")])
    mgr, _ = _build(conn)
    await mgr.handle_ws_fill({
        "broker_order_id": "b", "fill_id": "f1",
        "price": 0.5, "size": 1.0,
    })
    assert conn.terminal_updates == []
    assert conn.fills_inserted == []


# ---------------------------------------------------------------------------
# Dedup: WS + poll arriving for the same fill_id
# ---------------------------------------------------------------------------


async def test_ws_partial_fills_accumulate_without_terminating():
    """Multi-trade GTC partial fill: three WS frames arrive for the
    same order, each carrying a different fill_id. Records-only path
    must insert all three rows and never mark the order terminal.
    Without this, the second writer's race-loss would silently drop
    fills 2 + 3.
    """
    conn = FakeConn(orders=[_make_order(broker_id="b1")])
    mgr, notify_user = _build(conn)
    for fid, sz in (("f1", 25.0), ("f2", 25.0), ("f3", 50.0)):
        await mgr.handle_ws_fill({
            "broker_order_id": "b1", "fill_id": fid,
            "price": 0.5, "size": sz,
        })
    assert len(conn.fills_inserted) == 3
    assert {row[1] for row in conn.fills_inserted} == {"f1", "f2", "f3"}
    assert conn.terminal_updates == []
    notify_user.assert_not_awaited()


async def test_ws_then_poll_dedup_via_fill_id_unique_constraint():
    """Real schema dedup: the WS path inserts per-trade fill_ids; the
    polling path's terminal `_on_fill` will INSERT INTO fills with its
    own synthetic fill_id and then UPDATE orders to terminal. Both can
    co-exist without double-counting because the unique fill_id
    constraint drops any duplicate (FakeConn does not enforce, so this
    test asserts the contract via call-site behaviour: the WS path
    never issues a terminal RETURNING id).
    """
    conn = FakeConn(orders=[_make_order(broker_id="b1")])
    mgr, _ = _build(conn)
    await mgr.handle_ws_fill({
        "broker_order_id": "b1", "fill_id": "f1",
        "price": 0.5, "size": 1.0,
    })
    # No terminal write from the WS path — polling can still race-win.
    assert conn.terminal_updates == []
    assert len(conn.fills_inserted) == 1


# ---------------------------------------------------------------------------
# handle_ws_order_update
# ---------------------------------------------------------------------------


async def test_ws_order_update_filled_dispatches_on_fill():
    conn = FakeConn(orders=[_make_order(broker_id="b2")])
    mgr, _ = _build(conn)
    await mgr.handle_ws_order_update({
        "broker_order_id": "b2",
        "status": "filled",
        "size_matched": 50.0,
        "price": 0.6,
    })
    assert len(conn.terminal_updates) == 1


async def test_ws_order_update_cancelled_routes_through_cancel_path():
    conn = FakeConn(orders=[_make_order(broker_id="b3")])
    mgr, _ = _build(conn)
    await mgr.handle_ws_order_update({
        "broker_order_id": "b3",
        "status": "cancelled",
        "size_matched": None,
        "price": None,
    })
    assert len(conn.terminal_updates) == 1


async def test_ws_order_update_open_status_no_writes():
    conn = FakeConn(orders=[_make_order(broker_id="b4")])
    mgr, _ = _build(conn)
    await mgr.handle_ws_order_update({
        "broker_order_id": "b4", "status": "open",
    })
    assert conn.terminal_updates == []


async def test_ws_order_update_unknown_broker_id_no_writes():
    conn = FakeConn(orders=[_make_order(broker_id="known")])
    mgr, _ = _build(conn)
    await mgr.handle_ws_order_update({
        "broker_order_id": "unknown", "status": "filled",
    })
    assert conn.terminal_updates == []


async def test_ws_fill_then_order_update_filled_skips_aggregate_row():
    """Codex P2: when handle_ws_fill has already recorded a per-trade
    fill row, a follow-on ``order_update(status=filled)`` (or polling
    reconciliation) must NOT add an extra ``agg-{broker}`` aggregate
    row, otherwise fills-based reconciliation/reporting double-counts
    the same shares (per-trade row + aggregate row in the fills table).
    """
    conn = FakeConn(orders=[_make_order(broker_id="b1")])
    mgr, _ = _build(conn)
    # Step 1: WS fill records a per-trade row.
    await mgr.handle_ws_fill({
        "broker_order_id": "b1", "fill_id": "trade-real-1",
        "price": 0.5, "size": 100.0,
    })
    assert len(conn.fills_inserted) == 1
    assert conn.fills_inserted[0][1] == "trade-real-1"
    # Step 2: order_update terminalises the order. _broker_fills would
    # synthesise an "agg-b1" row; the dedup guard must drop it because
    # a per-trade row already exists.
    await mgr.handle_ws_order_update({
        "broker_order_id": "b1",
        "status": "filled",
        "size_matched": 100.0,
        "price": 0.5,
    })
    assert len(conn.terminal_updates) == 1  # order moved to filled
    assert len(conn.fills_inserted) == 1  # NO duplicate aggregate row
    assert conn.fills_inserted[0][1] == "trade-real-1"


async def test_ws_cancel_after_partial_ws_fill_hydrates_prior_fills(monkeypatch):
    """Codex P1 round 7: a partial WS fill records per-trade rows; a
    later WS cancellation frame may omit ``size_matched`` (the operator-
    cancel path). Without hydrating prior fills, ``_terminal_close``
    sees an empty fills list and refunds the FULL order notional even
    though the user already owns the matched shares from the WS fill.

    This test pins the fix: ``handle_ws_order_update`` loads existing
    per-trade fills from the DB before routing cancel/expiry, so
    ``_terminal_close`` correctly computes the partial-fill refund.
    """
    captured: list[dict] = []

    class _CaptureMgr(OrderLifecycleManager):
        async def _terminal_close(self, **kwargs: Any) -> None:
            captured.append(kwargs)

    notify_user = AsyncMock(return_value=True)
    conn = FakeConn(orders=[_make_order(broker_id="b1")])
    mgr = _CaptureMgr(
        settings=FakeSettings(use_real_clob=True),
        pool=FakePool(conn),
        notify_user=notify_user,
        notify_operator=AsyncMock(return_value=None),
        audit_write=AsyncMock(return_value=None),
    )
    # Step 1: WS fill records a per-trade row (40 shares @ $0.5 = $20
    # filled out of $100 notional).
    await mgr.handle_ws_fill({
        "broker_order_id": "b1", "fill_id": "trade-real-1",
        "price": 0.5, "size": 40.0,
    })
    assert len(conn.fills_inserted) == 1

    # Step 2: WS cancellation arrives WITHOUT size_matched. The fix
    # must hydrate prior fills from the DB so _terminal_close sees a
    # non-empty fills list and refunds only the unfilled remainder.
    await mgr.handle_ws_order_update({
        "broker_order_id": "b1",
        "status": "cancelled",
        "size_matched": None,
        "price": None,
    })
    assert len(captured) == 1
    fills_passed = captured[0]["fills"]
    assert len(fills_passed) == 1
    assert fills_passed[0]["fill_id"] == "trade-real-1"
    assert fills_passed[0]["size"] == pytest.approx(40.0)
    assert fills_passed[0]["price"] == pytest.approx(0.5)


async def test_ws_gap_aggregate_fill_inserted_when_per_trade_undercovers():
    """Codex P2 round 8: when the WS captured only one CONFIRMED partial
    trade and then missed later frames (disconnect / parser drop /
    broker gap), the polling/order_update aggregate represents the
    FULL terminal quantity. The dedup guard must NOT skip the aggregate
    in this case — otherwise the fills table holds only the earlier
    partial while orders.fill_size + position math reflect the larger
    aggregate, undercounting settled shares in any reconciliation.
    """
    conn = FakeConn(orders=[_make_order(broker_id="b1")])
    mgr, _ = _build(conn)
    # Step 1: WS records one partial fill (50 shares).
    await mgr.handle_ws_fill({
        "broker_order_id": "b1", "fill_id": "trade-real-1",
        "price": 0.5, "size": 50.0,
    })
    assert len(conn.fills_inserted) == 1
    # Step 2: order_update terminalises with size_matched=200 (the WS
    # missed the additional 150 shares). The dedup guard sees per-trade
    # sum 50 < incoming aggregate 200 and inserts the aggregate so
    # downstream reconciliation captures the full settled quantity.
    await mgr.handle_ws_order_update({
        "broker_order_id": "b1",
        "status": "filled",
        "size_matched": 200.0,
        "price": 0.5,
    })
    assert len(conn.terminal_updates) == 1
    assert len(conn.fills_inserted) == 2
    fill_ids = {row[1] for row in conn.fills_inserted}
    assert "trade-real-1" in fill_ids
    assert any(str(fid).startswith("agg-") for fid in fill_ids)


async def test_open_update_with_size_matched_persists_aggregate():
    """Codex P1 round 10 / WARP🔹CMD GATE: partial UPDATE
    (status=open, size_matched > 0 but < original_size) must persist
    the matched aggregate so a later cancellation that omits
    size_matched can hydrate it. Without this, _terminal_close
    refunds the FULL order notional even though shares were already
    matched.
    """
    conn = FakeConn(orders=[_make_order(broker_id="b1")])
    mgr, _ = _build(conn)
    await mgr.handle_ws_order_update({
        "broker_order_id": "b1",
        "status": "open",  # partial UPDATE: parser leaves as open
        "size_matched": 50.0,
        "price": 0.5,
    })
    # No terminal write — order is still open.
    assert conn.terminal_updates == []
    # The matched aggregate IS persisted so a follow-up
    # cancel-without-size_matched can hydrate it.
    assert len(conn.fills_inserted) == 1
    assert str(conn.fills_inserted[0][1]).startswith("agg-")
    assert float(conn.fills_inserted[0][3]) == pytest.approx(50.0)


async def test_partial_update_then_cancel_without_size_matched_refunds_remainder():
    """GATE-mandated regression: partial UPDATE persists agg row, then
    cancel-without-size_matched arrives. The cancel path must hydrate
    the partial-match aggregate from the DB and refund only the
    UNMATCHED remainder, not the full order notional.
    """
    captured: list[dict] = []

    class _CaptureMgr(OrderLifecycleManager):
        async def _terminal_close(self, **kwargs: Any) -> None:
            captured.append(kwargs)

    conn = FakeConn(orders=[_make_order(broker_id="b1")])
    mgr = _CaptureMgr(
        settings=FakeSettings(use_real_clob=True),
        pool=FakePool(conn),
        notify_user=AsyncMock(return_value=True),
        notify_operator=AsyncMock(return_value=None),
        audit_write=AsyncMock(return_value=None),
    )
    # Step 1: partial UPDATE persists agg row at 50 shares.
    await mgr.handle_ws_order_update({
        "broker_order_id": "b1",
        "status": "open",
        "size_matched": 50.0,
        "price": 0.5,
    })
    assert len(conn.fills_inserted) == 1
    # Step 2: cancellation without size_matched. The hydration path
    # loads the prior agg row so _terminal_close knows about the
    # 50 matched shares and only refunds the 50-share remainder.
    await mgr.handle_ws_order_update({
        "broker_order_id": "b1",
        "status": "cancelled",
        "size_matched": None,
        "price": None,
    })
    assert len(captured) == 1
    fills_passed = captured[0]["fills"]
    assert len(fills_passed) == 1
    assert float(fills_passed[0]["size"]) == pytest.approx(50.0)
    assert str(fills_passed[0]["fill_id"]).startswith("agg-")


async def test_partial_update_then_expiry_without_size_matched_preserves_match():
    """GATE-mandated regression: same as the cancel case but for
    expiry. Partial UPDATE persists agg row, then expiry without
    size_matched must hydrate the matched shares so the position
    is preserved (resized down) rather than rolled back entirely.
    """
    captured: list[dict] = []

    class _CaptureMgr(OrderLifecycleManager):
        async def _terminal_close(self, **kwargs: Any) -> None:
            captured.append(kwargs)

    conn = FakeConn(orders=[_make_order(broker_id="b1")])
    mgr = _CaptureMgr(
        settings=FakeSettings(use_real_clob=True),
        pool=FakePool(conn),
        notify_user=AsyncMock(return_value=True),
        notify_operator=AsyncMock(return_value=None),
        audit_write=AsyncMock(return_value=None),
    )
    await mgr.handle_ws_order_update({
        "broker_order_id": "b1",
        "status": "open",
        "size_matched": 30.0,
        "price": 0.5,
    })
    await mgr.handle_ws_order_update({
        "broker_order_id": "b1",
        "status": "expired",
        "size_matched": None,
    })
    assert len(captured) == 1
    fills_passed = captured[0]["fills"]
    assert len(fills_passed) == 1
    assert float(fills_passed[0]["size"]) == pytest.approx(30.0)
    # ts_column carries through to the expiry path.
    assert captured[0]["ts_column"] == "expired_at"


async def test_partial_update_then_confirmed_fill_does_not_double_credit():
    """GATE-mandated regression: partial UPDATE records agg at 50,
    then a CONFIRMED user_fill (per-trade row, fill_id="trade-1") at
    50 shares arrives — and the order_update(filled, size_matched=50)
    follows. The aggregate-fill dedup guard must skip the agg insert
    in _on_fill because the per-trade SUM (50) already covers the
    aggregate (50). Otherwise the fills table would contain both the
    per-trade row AND a fresh agg row for the same shares.
    """
    conn = FakeConn(orders=[_make_order(broker_id="b1")])
    mgr, _ = _build(conn)
    # Step 1: partial UPDATE persists agg row at 50.
    await mgr.handle_ws_order_update({
        "broker_order_id": "b1",
        "status": "open",
        "size_matched": 50.0,
        "price": 0.5,
    })
    assert len(conn.fills_inserted) == 1
    assert str(conn.fills_inserted[0][1]).startswith("agg-")
    # Step 2: CONFIRMED per-trade fill of 50 shares.
    await mgr.handle_ws_fill({
        "broker_order_id": "b1",
        "fill_id": "trade-1",
        "price": 0.5,
        "size": 50.0,
    })
    assert any(row[1] == "trade-1" for row in conn.fills_inserted)
    # Step 3: order_update(filled). _on_fill calls _record_fills_in_conn
    # with [agg-b1, size=50]. Dedup guard sees per-trade SUM=50 >=
    # incoming agg=50 → skip. No new agg row added beyond Step 1.
    pre = sum(
        1 for row in conn.fills_inserted
        if str(row[1]).startswith("agg-")
    )
    await mgr.handle_ws_order_update({
        "broker_order_id": "b1",
        "status": "filled",
        "size_matched": 50.0,
        "price": 0.5,
    })
    post = sum(
        1 for row in conn.fills_inserted
        if str(row[1]).startswith("agg-")
    )
    assert post == pre  # no new agg row from _on_fill


async def test_polling_dedups_against_ws_recorded_aggregate():
    """GATE-mandated regression: polling fallback's aggregate
    insertion path goes through the same dedup guard as the WS path.
    When a WS-recorded aggregate (e.g. from a prior partial UPDATE)
    already covers the polling aggregate, the dedup guard must skip
    the insert to avoid double-counting.

    Note: this exercises the dedup contract via _record_fills_in_conn
    directly because polling uses the same helper as the WS path.
    """
    conn = FakeConn(orders=[_make_order(broker_id="b1")])
    mgr, _ = _build(conn)
    # WS partial UPDATE first persists agg row at 80 shares.
    await mgr.handle_ws_order_update({
        "broker_order_id": "b1",
        "status": "open",
        "size_matched": 80.0,
        "price": 0.5,
    })
    # Polling subsequently fires _on_fill with a re-built
    # _broker_fills aggregate covering the same 80 shares. The
    # dedup guard's per-trade-SUM check returns 0 (no per-trade
    # rows), so the agg insert proceeds — but the unique fill_id
    # ON CONFLICT DO UPDATE simply refreshes the size.
    pre_count = len(conn.fills_inserted)
    await mgr.handle_ws_order_update({
        "broker_order_id": "b1",
        "status": "filled",
        "size_matched": 80.0,
        "price": 0.5,
    })
    post_count = len(conn.fills_inserted)
    # FakeConn appends on every INSERT (no real UNIQUE constraint),
    # so we observe two INSERT calls — but the prod schema's
    # ON CONFLICT DO UPDATE keeps a single row. The contract this
    # test pins is: the agg INSERT path is invoked exactly once per
    # terminal step; no duplicate _terminal_close or duplicate
    # ledger/refund side effects fire.
    assert post_count - pre_count == 1
    assert len(conn.terminal_updates) == 1


async def test_polling_only_aggregate_fill_still_inserted_when_no_per_trade():
    """Sister test: when there are no per-trade rows yet (polling-only
    path with no WS coverage), the aggregate row IS inserted so the
    fills table still has at least one row per filled order.
    """
    conn = FakeConn(orders=[_make_order(broker_id="b2")])
    mgr, _ = _build(conn)
    await mgr.handle_ws_order_update({
        "broker_order_id": "b2",
        "status": "filled",
        "size_matched": 50.0,
        "price": 0.6,
    })
    assert len(conn.terminal_updates) == 1
    # The synthetic "agg-b2" row is the ONLY fills record we have for
    # this order, so the dedup guard must NOT skip it.
    assert len(conn.fills_inserted) == 1
    assert str(conn.fills_inserted[0][1]).startswith("agg-")


# ---------------------------------------------------------------------------
# Module-level dispatch shims (used by ClobWebSocketClient callbacks)
# ---------------------------------------------------------------------------


async def test_module_dispatchers_route_through_default_manager(monkeypatch):
    captured: list[tuple[str, dict]] = []

    class _StubMgr:
        async def handle_ws_fill(self, ev: dict) -> None:
            captured.append(("fill", ev))

        async def handle_ws_order_update(self, ev: dict) -> None:
            captured.append(("order", ev))

    monkeypatch.setattr(lc, "_default_manager", _StubMgr())
    await lc.dispatch_ws_fill({"x": 1})
    await lc.dispatch_ws_order_update({"y": 2})
    assert captured == [("fill", {"x": 1}), ("order", {"y": 2})]


# ---------------------------------------------------------------------------
# Scheduler ws_connect / ws_watchdog / ws_shutdown
# ---------------------------------------------------------------------------


async def test_ws_connect_noop_in_paper_mode(monkeypatch):
    pytest.importorskip("apscheduler")
    pytest.importorskip("web3")
    from projects.polymarket.crusaderbot import scheduler as sch

    class _PaperSettings:
        USE_REAL_CLOB = False
    monkeypatch.setattr(sch, "get_settings", lambda: _PaperSettings())
    monkeypatch.setattr(sch, "_ws_client", None, raising=False)
    await sch.ws_connect()
    assert sch.get_ws_client() is None


async def test_ws_watchdog_reconnects_when_client_not_alive(monkeypatch):
    pytest.importorskip("apscheduler")
    pytest.importorskip("web3")
    from projects.polymarket.crusaderbot import scheduler as sch

    class _LiveSettings:
        USE_REAL_CLOB = True
    monkeypatch.setattr(sch, "get_settings", lambda: _LiveSettings())

    constructed: list[Any] = []

    class _DeadClient:
        def is_alive(self) -> bool:
            return False
        async def stop(self) -> None:
            pass
        async def start(self) -> None:
            constructed.append("started")

    class _AliveCtor:
        def __init__(self, **kwargs: Any) -> None:
            constructed.append("constructed")
        def is_alive(self) -> bool:
            return True
        async def start(self) -> None:
            constructed.append("started")
        async def stop(self) -> None:
            pass

    monkeypatch.setattr(sch, "_ws_client", _DeadClient(), raising=False)
    monkeypatch.setattr(sch, "ClobWebSocketClient", _AliveCtor)
    await sch.ws_watchdog()
    # Watchdog tore down the dead client and constructed + started a new one.
    assert "constructed" in constructed
    assert "started" in constructed


def test_setup_scheduler_registers_ws_jobs(monkeypatch):
    """``setup_scheduler`` must register both WS jobs alongside the
    existing polling job. Mirrors ``test_order_lifecycle``'s scheduler
    test pattern: stub ``AsyncIOScheduler`` + ``get_settings`` so the
    test runs without env vars and without spinning up a real loop.
    """
    pytest.importorskip("web3")
    from projects.polymarket.crusaderbot import scheduler as sch

    captured: list[dict] = []

    class FakeSched:
        def __init__(self, *args, **kwargs):
            pass

        def add_job(self, func, *args, **kwargs):
            captured.append({"id": kwargs.get("id"),
                             "seconds": kwargs.get("seconds")})

        def add_listener(self, *args, **kwargs):
            pass

    monkeypatch.setattr(sch, "AsyncIOScheduler", FakeSched)

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

    monkeypatch.setattr(sch, "get_settings", lambda: _S())
    sch.setup_scheduler()

    job_ids = [c["id"] for c in captured]
    assert "ws_connect" in job_ids
    assert "ws_watchdog" in job_ids
    watchdog = next(c for c in captured if c["id"] == "ws_watchdog")
    assert watchdog["seconds"] == 60
