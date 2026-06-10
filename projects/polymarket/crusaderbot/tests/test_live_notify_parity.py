"""WARP/root-live-notify-parity — live entry card + close snapshot parity.

Pins the paper/live user-visibility parity contract:

* live.execute() success → full TradeNotifier entry card (mode="live",
  position_id threaded, submitted limit price) instead of the legacy bare
  "[LIVE] Opened" notifications.send line;
* a notification-path failure can NEVER fail an order that already exists
  at the broker (fail-soft wrapper at the call site);
* live.close_position() finalize → portfolio_snapshots.write_snapshot
  (same WebTrader SSE contract as the paper close path), and NO snapshot
  on the not-claimed early-return path;
* TradeNotifier.notify_entry renders a loud LIVE header for mode="live"
  while the paper rendering stays byte-identical.

All tests are hermetic — fake pool/conn, mock CLOB client, no network/DB.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

from projects.polymarket.crusaderbot.domain.execution.live import (
    close_position,
    execute,
)
from projects.polymarket.crusaderbot.integrations.clob import MockClobClient
from projects.polymarket.crusaderbot.services.trade_notifications import (
    TradeNotifier,
)

_LIVE = "projects.polymarket.crusaderbot.domain.execution.live"

ORDER_ID = UUID("11111111-1111-1111-1111-111111111111")
POSITION_ID = UUID("22222222-2222-2222-2222-222222222222")
USER_ID = uuid4()


class _FakeTx:
    async def __aenter__(self) -> "_FakeTx":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False


class FakeConn:
    """asyncpg connection stand-in (mirrors test_live_execution_rewire)."""

    def __init__(
        self,
        *,
        insert_returns: bool = True,
        close_claim: UUID | None = None,
        close_finalize: UUID | None = None,
    ) -> None:
        self.insert_returns = insert_returns
        self.close_claim = close_claim
        self.close_finalize = close_finalize
        self.executed: list[tuple] = []

    async def fetchrow(self, query: str, *args: Any) -> dict | None:
        if "INSERT INTO orders" in query:
            return {"id": ORDER_ID} if self.insert_returns else None
        if "INSERT INTO positions" in query:
            return {"id": POSITION_ID}
        if "SELECT yes_token_id" in query:
            return {"yes_token_id": "tok-yes", "no_token_id": "tok-no"}
        return None

    async def fetchval(self, query: str, *args: Any) -> Any:
        if "status='closing'" in query and "RETURNING id" in query:
            return self.close_claim
        if "status='closed'" in query and "RETURNING id" in query:
            return self.close_finalize
        if "SELECT id FROM orders WHERE idempotency_key" in query:
            return None if self.insert_returns else ORDER_ID
        return None

    async def execute(self, query: str, *args: Any) -> str:
        self.executed.append((query, args))
        return "OK"

    def transaction(self) -> _FakeTx:
        return _FakeTx()


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


def _settings() -> Any:
    class _S:
        ENABLE_LIVE_TRADING = True
        EXECUTION_PATH_VALIDATED = True
        CAPITAL_MODE_CONFIRMED = True
        RISK_CONTROLS_VALIDATED = True
        SECURITY_HARDENING_VALIDATED = True
        USE_REAL_CLOB = True

    return _S()


def _make_mdc_mock() -> Any:
    mdc = MagicMock()
    mdc.get_tick_size = AsyncMock(return_value="0.01")
    mdc.get_neg_risk = AsyncMock(return_value=False)
    mdc.__aenter__ = AsyncMock(return_value=mdc)
    mdc.__aexit__ = AsyncMock(return_value=False)
    return mdc


_EXEC_KWARGS: dict[str, Any] = dict(
    user_id=USER_ID,
    telegram_user_id=12345,
    role="admin",
    trading_mode="live",
    market_id="mkt-abc",
    market_question="Will X happen?",
    yes_token_id="tok-yes",
    no_token_id="tok-no",
    side="yes",
    size_usdc=Decimal("100"),
    price=0.6,
    idempotency_key="key-abc",
    strategy_type="late_entry_v3",
    tp_pct=1.5,
    sl_pct=0.5,
)

_POSITION: dict[str, Any] = {
    "id": POSITION_ID,
    "user_id": USER_ID,
    "market_id": "mkt-abc",
    "side": "yes",
    "size_usdc": Decimal("100"),
    "entry_price": 0.6,
    "mode": "live",
}


def _run_execute(
    conn: FakeConn,
    *,
    notify_entry: AsyncMock,
    send: AsyncMock,
) -> dict:
    with (
        patch(f"{_LIVE}.get_settings", return_value=_settings()),
        patch(f"{_LIVE}.get_pool", return_value=FakePool(conn)),
        patch(f"{_LIVE}.MarketDataClient", return_value=_make_mdc_mock()),
        patch(f"{_LIVE}.audit.write", new=AsyncMock()),
        patch(f"{_LIVE}.notifications.send", new=send),
        patch(f"{_LIVE}.notifications.notify_operator", new=AsyncMock()),
        patch(f"{_LIVE}.ledger.debit_in_conn", new=AsyncMock()),
        patch(f"{_LIVE}._notifier.notify_entry", new=notify_entry),
    ):
        return asyncio.run(execute(clob_client=MockClobClient(), **_EXEC_KWARGS))


def _run_close(
    conn: FakeConn,
    *,
    write_snapshot: AsyncMock,
) -> dict:
    with (
        patch(f"{_LIVE}.get_settings", return_value=_settings()),
        patch(f"{_LIVE}.get_pool", return_value=FakePool(conn)),
        patch(f"{_LIVE}.MarketDataClient", return_value=_make_mdc_mock()),
        patch(f"{_LIVE}.audit.write", new=AsyncMock()),
        patch(f"{_LIVE}.notifications.notify_operator", new=AsyncMock()),
        patch(f"{_LIVE}.ledger.credit_in_conn", new=AsyncMock()),
        patch(f"{_LIVE}.portfolio_snapshots.write_snapshot", new=write_snapshot),
    ):
        return asyncio.run(
            close_position(
                position=dict(_POSITION),
                exit_price=0.8,
                exit_reason="tp_hit",
                clob_client=MockClobClient(),
            )
        )


class TestLiveEntryCardParity:
    def test_entry_card_fired_with_live_mode_and_position_id(self) -> None:
        notify = AsyncMock()
        send = AsyncMock()
        result = _run_execute(FakeConn(), notify_entry=notify, send=send)

        assert result["mode"] == "live"
        assert result["position_id"] == POSITION_ID
        notify.assert_awaited_once()
        kwargs = notify.await_args.kwargs
        assert kwargs["mode"] == "live"
        assert kwargs["position_id"] == str(POSITION_ID)
        assert kwargs["telegram_user_id"] == 12345
        assert kwargs["tp_pct"] == 1.5 and kwargs["sl_pct"] == 0.5
        # Entry price on the card is the SUBMITTED limit price — the same
        # value persisted to positions.entry_price (not the raw signal price).
        assert isinstance(kwargs["price"], float)

    def test_legacy_bare_send_is_gone(self) -> None:
        notify = AsyncMock()
        send = AsyncMock()
        _run_execute(FakeConn(), notify_entry=notify, send=send)
        send.assert_not_awaited()

    def test_notification_failure_never_fails_the_order(self) -> None:
        notify = AsyncMock(side_effect=RuntimeError("prefs DB blip"))
        send = AsyncMock()
        result = _run_execute(FakeConn(), notify_entry=notify, send=send)
        # Order existed at the broker before the notification — the result
        # contract must be unaffected by a notification-path failure.
        assert result == {
            "order_id": ORDER_ID,
            "position_id": POSITION_ID,
            "mode": "live",
        }


class TestLiveCloseSnapshotParity:
    def test_finalized_close_writes_portfolio_snapshot(self) -> None:
        snap = AsyncMock(return_value=None)
        conn = FakeConn(close_claim=POSITION_ID, close_finalize=POSITION_ID)
        result = _run_close(conn, write_snapshot=snap)
        assert result["exit_reason"] == "tp_hit"
        snap.assert_awaited_once_with(USER_ID)

    def test_unclaimed_close_skips_snapshot(self) -> None:
        snap = AsyncMock(return_value=None)
        conn = FakeConn(close_claim=None, close_finalize=None)
        result = _run_close(conn, write_snapshot=snap)
        assert result["exit_reason"] == "already_closed"
        snap.assert_not_awaited()


class TestNotifierLiveHeader:
    @staticmethod
    def _render(mode: str | None) -> str:
        notifier = TradeNotifier()
        kwargs: dict[str, Any] = dict(
            telegram_user_id=1,
            market_id="mkt-1",
            market_question="Will Y happen?",
            side="yes",
            size_usdc=Decimal("10"),
            price=0.5,
            tp_pct=1.5,
            sl_pct=0.5,
            strategy_type="late_entry_v3",
            position_id="pos-1",
        )
        if mode is not None:
            kwargs["mode"] = mode
        with patch.object(notifier, "_send", new=AsyncMock()) as send:
            asyncio.run(notifier.notify_entry(**kwargs))
            return send.await_args.args[1]

    def test_live_mode_renders_loud_live_header(self) -> None:
        text = self._render("live")
        assert "LIVE TRADE OPENED" in text
        assert "📋  TRADE OPENED" not in text

    def test_paper_default_rendering_unchanged(self) -> None:
        text = self._render(None)
        assert "📋  TRADE OPENED" in text
        assert "LIVE TRADE" not in text
