"""Tests for CLOB tick_size/neg_risk threading through post_order call sites.

Covers:
  * live.execute()        — BUY entry: tick_size+neg_risk fetched and forwarded
  * live.execute()        — graceful degradation when MarketDataClient raises
  * live.close_position() — SELL close: tick_size+neg_risk fetched and forwarded
  * lifecycle._on_slippage_retry() — retry path uses fetched tick_size for price widen
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from projects.polymarket.crusaderbot.domain.execution.live import (
    close_position,
    execute,
)
from projects.polymarket.crusaderbot.domain.execution.lifecycle import OrderLifecycleManager


# ---------------------------------------------------------------------------
# Shared fake DB / helpers
# ---------------------------------------------------------------------------

ORDER_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
POSITION_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
USER_ID = uuid4()
TOKEN_YES = "tok-yes-123"
TOKEN_NO = "tok-no-123"


class _FakeTx:
    async def __aenter__(self) -> "_FakeTx":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False


class FakeConn:
    def __init__(
        self,
        *,
        insert_returns: bool = True,
        market_row: dict | None = None,
        close_claim: UUID | None = None,
        close_finalize: UUID | None = None,
    ) -> None:
        self.insert_returns = insert_returns
        self.market_row = market_row or {
            "yes_token_id": TOKEN_YES,
            "no_token_id": TOKEN_NO,
        }
        self.close_claim = close_claim
        self.close_finalize = close_finalize
        self.executed: list[tuple] = []

    async def fetchrow(self, query: str, *args: Any) -> dict | None:
        if "INSERT INTO orders" in query:
            return {"id": ORDER_ID} if self.insert_returns else None
        if "INSERT INTO positions" in query:
            return {"id": POSITION_ID}
        if "SELECT yes_token_id" in query:
            return self.market_row
        return None

    async def fetchval(self, query: str, *args: Any) -> Any:
        if "status='closing'" in query:
            return self.close_claim
        if "status='closed'" in query:
            return self.close_finalize
        if "SELECT id FROM orders WHERE idempotency_key" in query:
            return None  # not a duplicate — proceed with fetch
        return None

    async def fetch(self, query: str, *args: Any) -> list:
        return []

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


def _settings(
    *,
    enable_live: bool = True,
    exec_validated: bool = True,
    capital_confirmed: bool = True,
    risk_controls_validated: bool = True,
    security_hardening_validated: bool = True,
    use_real_clob: bool = True,
) -> Any:
    class _S:
        ENABLE_LIVE_TRADING = enable_live
        EXECUTION_PATH_VALIDATED = exec_validated
        CAPITAL_MODE_CONFIRMED = capital_confirmed
        RISK_CONTROLS_VALIDATED = risk_controls_validated
        SECURITY_HARDENING_VALIDATED = security_hardening_validated
        USE_REAL_CLOB = use_real_clob
        ORDER_POLL_MAX_ATTEMPTS = 5

    return _S()


_EXEC_KWARGS: dict[str, Any] = dict(
    user_id=USER_ID,
    telegram_user_id=12345,
    role="admin",
    trading_mode="live",
    market_id="mkt-abc",
    market_question="Will X happen?",
    yes_token_id=TOKEN_YES,
    no_token_id=TOKEN_NO,
    side="yes",
    size_usdc=Decimal("100"),
    price=0.6,
    idempotency_key="key-abc",
    strategy_type="copy_trade",
    tp_pct=None,
    sl_pct=None,
)


def _fake_mdc(tick_size: str = "0.001", neg_risk: bool = True) -> Any:
    """Return a MarketDataClient async context manager double."""
    mdc = MagicMock()
    mdc.get_tick_size = AsyncMock(return_value=tick_size)
    mdc.get_neg_risk = AsyncMock(return_value=neg_risk)
    mdc.__aenter__ = AsyncMock(return_value=mdc)
    mdc.__aexit__ = AsyncMock(return_value=False)
    return mdc


# ---------------------------------------------------------------------------
# live.execute() — BUY entry
# ---------------------------------------------------------------------------

class TestExecuteTickSize:
    def _run(self, clob_client: Any, mdc: Any, **overrides: Any) -> dict:
        conn = FakeConn()
        pool = FakePool(conn)
        settings_obj = _settings()
        with (
            patch(
                "projects.polymarket.crusaderbot.domain.execution.live.get_settings",
                return_value=settings_obj,
            ),
            patch(
                "projects.polymarket.crusaderbot.domain.execution.live.get_pool",
                return_value=pool,
            ),
            patch(
                "projects.polymarket.crusaderbot.domain.execution.live.MarketDataClient",
                return_value=mdc,
            ),
            patch(
                "projects.polymarket.crusaderbot.domain.execution.live.audit.write",
                new=AsyncMock(),
            ),
            patch(
                "projects.polymarket.crusaderbot.domain.execution.live.notifications.send",
                new=AsyncMock(),
            ),
            patch(
                "projects.polymarket.crusaderbot.domain.execution.live.notifications.notify_operator",
                new=AsyncMock(),
            ),
            patch(
                "projects.polymarket.crusaderbot.domain.execution.live.ledger.debit_in_conn",
                new=AsyncMock(),
            ),
        ):
            kwargs = {**_EXEC_KWARGS, "clob_client": clob_client, **overrides}
            return asyncio.run(execute(**kwargs))

    def test_tick_size_and_neg_risk_forwarded_to_post_order(self) -> None:
        """execute() must pass fetched tick_size + neg_risk to post_order."""
        clob = MagicMock()
        clob.post_order = AsyncMock(return_value={"orderID": "ord-1"})
        mdc = _fake_mdc(tick_size="0.001", neg_risk=True)

        self._run(clob, mdc)

        call_kwargs = clob.post_order.call_args.kwargs
        assert call_kwargs["tick_size"] == "0.001"
        assert call_kwargs["neg_risk"] is True

    def test_mdc_failure_raises_live_pre_submit_error(self) -> None:
        """execute() must raise LivePreSubmitError on metadata fetch failure.

        Submitting a new entry with wrong tick_size would cause a CLOB rejection
        as a post-submit ambiguous error (worse than a clean pre-submit abort).
        Unwind paths (close_position, slippage_retry) keep graceful degradation.
        """
        from projects.polymarket.crusaderbot.domain.execution.live import (
            LivePreSubmitError,
        )

        clob = MagicMock()
        clob.post_order = AsyncMock(return_value={"orderID": "ord-2"})

        broken_mdc = MagicMock()
        broken_mdc.__aenter__ = AsyncMock(side_effect=RuntimeError("network error"))
        broken_mdc.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(LivePreSubmitError, match="CLOB market metadata unavailable"):
            self._run(clob, broken_mdc)

    def test_non_default_tick_size_affects_price_widen(self) -> None:
        """Real tick_size is used in compute_aggressive_limit_price, not hardcoded 0.01."""
        clob = MagicMock()
        clob.post_order = AsyncMock(return_value={"orderID": "ord-3"})
        mdc = _fake_mdc(tick_size="0.001", neg_risk=False)

        self._run(clob, mdc, best_ask=0.60, best_bid=0.58)

        submitted_price = clob.post_order.call_args.kwargs["price"]
        # With tick_size=0.001 and offset_ticks=1, price = best_ask + 0.001 = 0.601
        # With old hardcoded 0.01, price would be 0.61
        assert abs(submitted_price - 0.601) < 1e-9, f"Expected 0.601, got {submitted_price}"


# ---------------------------------------------------------------------------
# live.close_position() — SELL close
# ---------------------------------------------------------------------------

class TestClosePositionTickSize:
    def _run(self, clob_client: Any, mdc: Any) -> dict:
        conn = FakeConn(
            close_claim=POSITION_ID,
            close_finalize=POSITION_ID,
        )
        pool = FakePool(conn)
        settings_obj = _settings()
        position = {
            "id": POSITION_ID,
            "user_id": USER_ID,
            "market_id": "mkt-abc",
            "side": "yes",
            "size_usdc": Decimal("100"),
            "entry_price": 0.6,
            "strategy_type": "copy_trade",
            "telegram_user_id": 12345,
        }
        with (
            patch(
                "projects.polymarket.crusaderbot.domain.execution.live.get_settings",
                return_value=settings_obj,
            ),
            patch(
                "projects.polymarket.crusaderbot.domain.execution.live.get_pool",
                return_value=pool,
            ),
            patch(
                "projects.polymarket.crusaderbot.domain.execution.live.MarketDataClient",
                return_value=mdc,
            ),
            patch(
                "projects.polymarket.crusaderbot.domain.execution.live.audit.write",
                new=AsyncMock(),
            ),
            patch(
                "projects.polymarket.crusaderbot.domain.execution.live.notifications.send",
                new=AsyncMock(),
            ),
            patch(
                "projects.polymarket.crusaderbot.domain.execution.live.notifications.notify_operator",
                new=AsyncMock(),
            ),
            patch(
                "projects.polymarket.crusaderbot.domain.execution.live.ledger.credit_in_conn",
                new=AsyncMock(),
            ),
        ):
            return asyncio.run(
                close_position(
                    position=position,
                    exit_price=0.65,
                    exit_reason="tp",
                    clob_client=clob_client,
                )
            )

    def test_tick_size_and_neg_risk_forwarded_to_post_order(self) -> None:
        clob = MagicMock()
        clob.post_order = AsyncMock(return_value={})
        mdc = _fake_mdc(tick_size="0.01", neg_risk=False)

        self._run(clob, mdc)

        call_kwargs = clob.post_order.call_args.kwargs
        assert call_kwargs["tick_size"] == "0.01"
        assert call_kwargs["neg_risk"] is False

    def test_defaults_used_on_mdc_failure(self) -> None:
        clob = MagicMock()
        clob.post_order = AsyncMock(return_value={})

        broken_mdc = MagicMock()
        broken_mdc.__aenter__ = AsyncMock(side_effect=RuntimeError("timeout"))
        broken_mdc.__aexit__ = AsyncMock(return_value=False)

        self._run(clob, broken_mdc)

        call_kwargs = clob.post_order.call_args.kwargs
        assert call_kwargs["tick_size"] == "0.01"
        assert call_kwargs["neg_risk"] is False


# ---------------------------------------------------------------------------
# lifecycle._on_slippage_retry() — slippage retry path
# ---------------------------------------------------------------------------

class TestSlippageRetryTickSize:
    def _make_manager(self, pool: FakePool, mdc: Any) -> OrderLifecycleManager:
        settings_obj = _settings()
        mgr = OrderLifecycleManager(settings=settings_obj, pool=pool)
        return mgr

    def _run_retry(
        self,
        clob_client: Any,
        mdc: Any,
        order: dict,
    ) -> None:
        conn = FakeConn(
            market_row={"yes_token_id": TOKEN_YES, "no_token_id": TOKEN_NO},
        )
        pool = FakePool(conn)
        mgr = self._make_manager(pool, mdc)

        with patch(
            "projects.polymarket.crusaderbot.domain.execution.lifecycle.MarketDataClient",
            return_value=mdc,
        ):
            asyncio.run(mgr._on_slippage_retry(order=order, attempts=1, client=clob_client))

    def _order(self, price: float = 0.60) -> dict:
        return {
            "id": ORDER_ID,
            "user_id": USER_ID,
            "market_id": "mkt-abc",
            "side": "yes",
            "size_usdc": Decimal("50"),
            "price": price,
            "polymarket_order_id": "broker-111",
            "slippage_retry_count": 0,
        }

    def test_tick_size_and_neg_risk_forwarded_to_post_order(self) -> None:
        clob = MagicMock()
        clob.cancel_order = AsyncMock(return_value={})
        clob.post_order = AsyncMock(return_value={"orderID": "new-ord"})
        mdc = _fake_mdc(tick_size="0.001", neg_risk=True)

        self._run_retry(clob, mdc, self._order())

        call_kwargs = clob.post_order.call_args.kwargs
        assert call_kwargs["tick_size"] == "0.001"
        assert call_kwargs["neg_risk"] is True

    def test_price_widen_uses_fetched_tick_size(self) -> None:
        """Real tick_size=0.001 must widen price by 0.001, not the old hardcoded 0.01."""
        clob = MagicMock()
        clob.cancel_order = AsyncMock(return_value={})
        clob.post_order = AsyncMock(return_value={"orderID": "new-ord"})
        mdc = _fake_mdc(tick_size="0.001", neg_risk=False)

        order = self._order(price=0.60)
        self._run_retry(clob, mdc, order)

        submitted_price = clob.post_order.call_args.kwargs["price"]
        # tick_size=0.001: new_limit = round(min(0.99, 0.60 + 0.001), 4) = 0.601
        assert abs(submitted_price - 0.601) < 1e-9, f"Expected 0.601, got {submitted_price}"

    def test_mdc_failure_aborts_resubmit(self) -> None:
        """MDC failure must abort the re-submit (return early, no post_order call).

        The original GTC order has already been cancelled; a replacement with
        wrong tick_size would cause a post-submit ambiguous rejection on
        0.001-tick or neg-risk markets. Mirrors the post_order exception handler
        behavior: return without advancing slippage_retry_count.
        """
        clob = MagicMock()
        clob.cancel_order = AsyncMock(return_value={})
        clob.post_order = AsyncMock(return_value={"orderID": "new-ord"})

        broken_mdc = MagicMock()
        broken_mdc.__aenter__ = AsyncMock(side_effect=RuntimeError("fetch failed"))
        broken_mdc.__aexit__ = AsyncMock(return_value=False)

        self._run_retry(clob, broken_mdc, self._order())

        clob.post_order.assert_not_called()
