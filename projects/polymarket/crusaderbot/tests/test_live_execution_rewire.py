"""Unit tests for Phase 4B live execution rewire.

Covers:
  * Guard routing: all 3 env guards missing → MockClobClient path (no real submit)
  * Dry-run mode: USE_REAL_CLOB=True, ENABLE_LIVE_TRADING=False → log + mock fill
  * Idempotency: duplicate idempotency_key → "duplicate" status, no second submit
  * GTC dispatch: post_order called with order_type="GTC"
  * FOK dispatch: post_order called with order_type="FOK"
  * Auth failure (ClobAuthError) → LivePreSubmitError (pre-submit, safe to fallback)
  * Network failure (non-ClobAuthError) → LivePostSubmitError (ambiguous, no fallback)
  * assert_live_guards: each of the three env guards in isolation + USE_REAL_CLOB=False
  * close_position: uses client.post_order(side="SELL")
  * close_position: already-closing position returns early without submit

No real DB — asyncpg.Pool and Connection are replaced with async-context-manager
doubles. No real network — ClobClientProtocol injected via clob_client parameter.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from projects.polymarket.crusaderbot.domain.execution.live import (
    LivePostSubmitError,
    LivePreSubmitError,
    assert_live_guards,
    close_position,
    execute,
)
from projects.polymarket.crusaderbot.integrations.clob import (
    ClobAuthError,
    ClobConfigError,
    MockClobClient,
)


# ---------------------------------------------------------------------------
# Fake DB helpers
# ---------------------------------------------------------------------------

ORDER_ID = UUID("11111111-1111-1111-1111-111111111111")
POSITION_ID = UUID("22222222-2222-2222-2222-222222222222")
USER_ID = uuid4()


class FakeConn:
    """asyncpg connection stand-in."""

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
            "yes_token_id": "tok-yes",
            "no_token_id": "tok-no",
        }
        self.close_claim = close_claim
        self.close_finalize = close_finalize
        self.executed: list[tuple] = []
        self._call = 0

    async def fetchrow(self, query: str, *args: Any) -> dict | None:
        self._call += 1
        if "INSERT INTO orders" in query:
            if self.insert_returns:
                return {"id": ORDER_ID}
            return None
        if "INSERT INTO positions" in query:
            return {"id": POSITION_ID}
        if "SELECT yes_token_id" in query:
            return self.market_row
        return None

    async def fetchval(self, query: str, *args: Any) -> Any:
        if "status='closing'" in query and "RETURNING id" in query:
            return self.close_claim
        if "status='closed'" in query and "RETURNING id" in query:
            return self.close_finalize
        return None

    async def execute(self, query: str, *args: Any) -> str:
        self.executed.append((query, args))
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


# ---------------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------------

def _settings(
    *,
    enable_live: bool = True,
    exec_validated: bool = True,
    capital_confirmed: bool = True,
    use_real_clob: bool = True,
) -> Any:
    class _S:
        ENABLE_LIVE_TRADING = enable_live
        EXECUTION_PATH_VALIDATED = exec_validated
        CAPITAL_MODE_CONFIRMED = capital_confirmed
        USE_REAL_CLOB = use_real_clob

    return _S()


# ---------------------------------------------------------------------------
# Shared execute() wiring
# ---------------------------------------------------------------------------

_EXEC_KWARGS: dict[str, Any] = dict(
    user_id=USER_ID,
    telegram_user_id=12345,
    access_tier=4,
    trading_mode="live",
    market_id="mkt-abc",
    market_question="Will X happen?",
    yes_token_id="tok-yes",
    no_token_id="tok-no",
    side="yes",
    size_usdc=Decimal("100"),
    price=0.6,
    idempotency_key="key-abc",
    strategy_type="copy_trade",
    tp_pct=None,
    sl_pct=None,
)


def _run_execute(conn: FakeConn, settings_obj: Any, client: Any, **overrides: Any) -> dict:
    pool = FakePool(conn)
    with (
        patch("projects.polymarket.crusaderbot.domain.execution.live.get_settings",
              return_value=settings_obj),
        patch("projects.polymarket.crusaderbot.domain.execution.live.get_pool",
              return_value=pool),
        patch("projects.polymarket.crusaderbot.domain.execution.live.audit.write",
              new=AsyncMock()),
        patch("projects.polymarket.crusaderbot.domain.execution.live.notifications.send",
              new=AsyncMock()),
        patch("projects.polymarket.crusaderbot.domain.execution.live.notifications.notify_operator",
              new=AsyncMock()),
        patch("projects.polymarket.crusaderbot.domain.execution.live.ledger.debit_in_conn",
              new=AsyncMock()),
    ):
        kwargs = {**_EXEC_KWARGS, "clob_client": client, **overrides}
        return asyncio.run(execute(**kwargs))


# ---------------------------------------------------------------------------
# assert_live_guards tests
# ---------------------------------------------------------------------------

class TestAssertLiveGuards:
    def test_all_guards_pass(self) -> None:
        s = _settings()
        with patch("projects.polymarket.crusaderbot.domain.execution.live.get_settings",
                   return_value=s):
            assert_live_guards(access_tier=4, trading_mode="live")

    def test_enable_live_trading_false_raises(self) -> None:
        s = _settings(enable_live=False)
        with (
            patch("projects.polymarket.crusaderbot.domain.execution.live.get_settings",
                  return_value=s),
            pytest.raises(LivePreSubmitError, match="ENABLE_LIVE_TRADING"),
        ):
            assert_live_guards(access_tier=4, trading_mode="live")

    def test_execution_path_not_validated_raises(self) -> None:
        s = _settings(exec_validated=False)
        with (
            patch("projects.polymarket.crusaderbot.domain.execution.live.get_settings",
                  return_value=s),
            pytest.raises(LivePreSubmitError, match="EXECUTION_PATH_VALIDATED"),
        ):
            assert_live_guards(access_tier=4, trading_mode="live")

    def test_capital_mode_not_confirmed_raises(self) -> None:
        s = _settings(capital_confirmed=False)
        with (
            patch("projects.polymarket.crusaderbot.domain.execution.live.get_settings",
                  return_value=s),
            pytest.raises(LivePreSubmitError, match="CAPITAL_MODE_CONFIRMED"),
        ):
            assert_live_guards(access_tier=4, trading_mode="live")

    def test_use_real_clob_false_raises(self) -> None:
        """USE_REAL_CLOB=False with all other guards set → LivePreSubmitError.

        Codex P1 finding: MockClobClient with all live guards enabled would
        insert mode='live' rows and debit the ledger without sending any real
        order to Polymarket — phantom live exposure. USE_REAL_CLOB is now a
        required guard for live execution.
        """
        s = _settings(use_real_clob=False)
        with (
            patch("projects.polymarket.crusaderbot.domain.execution.live.get_settings",
                  return_value=s),
            pytest.raises(LivePreSubmitError, match="USE_REAL_CLOB must be True"),
        ):
            assert_live_guards(access_tier=4, trading_mode="live")

    def test_low_tier_raises(self) -> None:
        s = _settings()
        with (
            patch("projects.polymarket.crusaderbot.domain.execution.live.get_settings",
                  return_value=s),
            pytest.raises(LivePreSubmitError, match="tier 3"),
        ):
            assert_live_guards(access_tier=3, trading_mode="live")

    def test_paper_trading_mode_raises(self) -> None:
        s = _settings()
        with (
            patch("projects.polymarket.crusaderbot.domain.execution.live.get_settings",
                  return_value=s),
            pytest.raises(LivePreSubmitError, match="trading_mode=paper"),
        ):
            assert_live_guards(access_tier=4, trading_mode="paper")


# ---------------------------------------------------------------------------
# Dry-run mode
# ---------------------------------------------------------------------------

class TestDryRunMode:
    def test_dry_run_when_use_real_clob_true_enable_live_false(self) -> None:
        """USE_REAL_CLOB=True + ENABLE_LIVE_TRADING=False → dry_run, no DB write."""
        s = _settings(use_real_clob=True, enable_live=False)
        conn = FakeConn()
        # Use a real MockClobClient — its post_order must NOT be called.
        client = MockClobClient()
        result = _run_execute(conn, s, client)
        assert result["status"] == "dry_run"
        assert result["_mock"] is True
        # No order inserted — idempotency INSERT never reached.
        assert conn._call == 0

    def test_dry_run_not_triggered_when_enable_live_true(self) -> None:
        """All guards set → normal path even when USE_REAL_CLOB=True."""
        s = _settings(use_real_clob=True, enable_live=True)
        conn = FakeConn()
        client = MockClobClient()
        result = _run_execute(conn, s, client)
        assert result.get("status") != "dry_run"
        assert "order_id" in result

    def test_dry_run_not_triggered_when_use_real_clob_false(self) -> None:
        """USE_REAL_CLOB=False → MockClobClient; no dry-run intercept."""
        s = _settings(use_real_clob=False, enable_live=False)
        conn = FakeConn()
        client = MockClobClient()
        # ENABLE_LIVE_TRADING=False → assert_live_guards will raise LivePreSubmitError
        # (dry-run only fires when USE_REAL_CLOB=True).
        with pytest.raises(LivePreSubmitError, match="ENABLE_LIVE_TRADING"):
            _run_execute(conn, s, client)


# ---------------------------------------------------------------------------
# Guard routing — injected mock vs real path
# ---------------------------------------------------------------------------

class TestGuardRouting:
    def test_all_guards_set_submits_via_clob_client(self) -> None:
        s = _settings()
        conn = FakeConn()
        client = MockClobClient()
        result = _run_execute(conn, s, client)
        assert result["mode"] == "live"
        assert "order_id" in result
        # Injected client must have received the order.
        assert len(client.open_orders()) == 1

    def test_guards_fail_raise_live_pre_submit_error(self) -> None:
        s = _settings(exec_validated=False)
        conn = FakeConn()
        client = MockClobClient()
        with pytest.raises(LivePreSubmitError, match="EXECUTION_PATH_VALIDATED"):
            _run_execute(conn, s, client)
        # No order submitted to client.
        assert client.open_orders() == []


# ---------------------------------------------------------------------------
# GTC / FOK dispatch
# ---------------------------------------------------------------------------

class TestOrderTypeDispatch:
    def _run_and_get_order(self, order_type: str) -> dict:
        s = _settings()
        conn = FakeConn()
        client = MockClobClient()
        _run_execute(conn, s, client, order_type=order_type)
        orders = client.open_orders()
        assert len(orders) == 1
        return orders[0]

    def test_gtc_order_type_passed_through(self) -> None:
        order = self._run_and_get_order("GTC")
        assert order["orderType"] == "GTC"

    def test_fok_order_type_passed_through(self) -> None:
        order = self._run_and_get_order("FOK")
        assert order["orderType"] == "FOK"

    def test_default_order_type_is_gtc(self) -> None:
        s = _settings()
        conn = FakeConn()
        client = MockClobClient()
        # No order_type kwarg → default should be GTC.
        _run_execute(conn, s, client)
        orders = client.open_orders()
        assert orders[0]["orderType"] == "GTC"


# ---------------------------------------------------------------------------
# Idempotency key
# ---------------------------------------------------------------------------

class TestIdempotencyKey:
    def test_duplicate_key_returns_duplicate_status(self) -> None:
        """ON CONFLICT DO NOTHING → execute returns {status: 'duplicate'}."""
        s = _settings()
        conn = FakeConn(insert_returns=False)
        client = MockClobClient()
        result = _run_execute(conn, s, client)
        assert result["status"] == "duplicate"
        # No order submitted to broker.
        assert client.open_orders() == []

    def test_unique_key_proceeds_to_submit(self) -> None:
        s = _settings()
        conn = FakeConn(insert_returns=True)
        client = MockClobClient()
        result = _run_execute(conn, s, client)
        assert "order_id" in result


# ---------------------------------------------------------------------------
# Exception classification
# ---------------------------------------------------------------------------

class TestExceptionClassification:
    def test_clob_auth_error_becomes_live_pre_submit_error(self) -> None:
        """ClobAuthError (signing failure, no network) → LivePreSubmitError."""
        s = _settings()
        conn = FakeConn()

        bad_client = AsyncMock()
        bad_client.post_order = AsyncMock(
            side_effect=ClobAuthError("bad key")
        )
        with pytest.raises(LivePreSubmitError, match="prepare failed"):
            _run_execute(conn, s, bad_client)
        # Order marked 'failed' in DB.
        assert any("failed" in str(e[0]) for e in conn.executed)

    def test_generic_error_becomes_live_post_submit_error(self) -> None:
        """Network/timeout error → LivePostSubmitError (ambiguous, no fallback)."""
        s = _settings()
        conn = FakeConn()

        bad_client = AsyncMock()
        bad_client.post_order = AsyncMock(
            side_effect=RuntimeError("connection timeout")
        )
        with pytest.raises(LivePostSubmitError, match="ambiguous submit"):
            _run_execute(conn, s, bad_client)
        # Order marked 'unknown' in DB.
        assert any("unknown" in str(e[0]) for e in conn.executed)

    def test_clob_config_error_becomes_live_pre_submit_error(self) -> None:
        """ClobConfigError from get_clob_client() → LivePreSubmitError (safe fallback).

        Codex P2 finding: when all live guards pass but CLOB credentials are
        missing/invalid, get_clob_client() raises ClobConfigError before any DB
        write or broker call. The router only catches LivePreSubmitError for
        paper fallback — unwrapped ClobConfigError drops the signal entirely.
        """
        s = _settings()
        conn = FakeConn()
        with (
            patch(
                "projects.polymarket.crusaderbot.domain.execution.live.get_clob_client",
                side_effect=ClobConfigError("missing CLOB credentials"),
            ),
            pytest.raises(LivePreSubmitError, match="CLOB client config error"),
        ):
            _run_execute(conn, s, client=None)

    def test_clob_auth_error_during_construction_becomes_live_pre_submit_error(self) -> None:
        """ClobAuthError raised by get_clob_client() (malformed key) → LivePreSubmitError.

        Codex P1 finding: get_clob_client() can raise ClobAuthError during
        adapter construction (e.g. invalid POLYMARKET_PRIVATE_KEY format) before
        any SELL is submitted. Previously only ClobConfigError was caught here,
        letting ClobAuthError escape as an untyped exception that the router
        cannot paper-fallback on.
        """
        s = _settings()
        conn = FakeConn()
        with (
            patch(
                "projects.polymarket.crusaderbot.domain.execution.live.get_clob_client",
                side_effect=ClobAuthError("malformed private key"),
            ),
            pytest.raises(LivePreSubmitError, match="CLOB client config error"),
        ):
            _run_execute(conn, s, client=None)


# ---------------------------------------------------------------------------
# close_position
# ---------------------------------------------------------------------------

_POSITION: dict[str, Any] = {
    "id": POSITION_ID,
    "user_id": USER_ID,
    "market_id": "mkt-abc",
    "side": "yes",
    "size_usdc": Decimal("100"),
    "entry_price": 0.6,
    "mode": "live",
}


def _run_close(
    conn: FakeConn,
    settings_obj: Any,
    client: Any,
    position: dict | None = None,
) -> dict:
    pool = FakePool(conn)
    pos = position or _POSITION
    with (
        patch("projects.polymarket.crusaderbot.domain.execution.live.get_settings",
              return_value=settings_obj),
        patch("projects.polymarket.crusaderbot.domain.execution.live.get_pool",
              return_value=pool),
        patch("projects.polymarket.crusaderbot.domain.execution.live.audit.write",
              new=AsyncMock()),
        patch("projects.polymarket.crusaderbot.domain.execution.live.ledger.credit_in_conn",
              new=AsyncMock()),
    ):
        return asyncio.run(
            close_position(
                position=pos,
                exit_price=0.8,
                exit_reason="tp",
                clob_client=client,
            )
        )


class TestClosePosition:
    def test_close_submits_sell_via_clob_client(self) -> None:
        conn = FakeConn(
            close_claim=POSITION_ID,
            close_finalize=POSITION_ID,
        )
        s = _settings()
        client = MockClobClient()
        result = _run_close(conn, s, client)
        assert "pnl_usdc" in result
        # Client received a SELL order.
        orders = client.open_orders()
        assert len(orders) == 1
        assert orders[0]["side"] == "SELL"

    def test_close_uses_gtc_order_type(self) -> None:
        conn = FakeConn(
            close_claim=POSITION_ID,
            close_finalize=POSITION_ID,
        )
        s = _settings()
        client = MockClobClient()
        _run_close(conn, s, client)
        assert client.open_orders()[0]["orderType"] == "GTC"

    def test_close_skips_when_already_closing(self) -> None:
        """claim UPDATE returns None (row not open) → early return, no submit."""
        conn = FakeConn(
            close_claim=None,  # already closing/closed
            close_finalize=POSITION_ID,
        )
        s = _settings()
        client = MockClobClient()
        result = _run_close(conn, s, client)
        assert result["exit_reason"] == "already_closed"
        assert client.open_orders() == []

    def test_close_rolls_back_claim_on_submit_failure(self) -> None:
        conn = FakeConn(
            close_claim=POSITION_ID,
            close_finalize=POSITION_ID,
        )
        s = _settings()
        bad_client = AsyncMock()
        bad_client.post_order = AsyncMock(side_effect=RuntimeError("net fail"))
        with pytest.raises(RuntimeError, match="net fail"):
            _run_close(conn, s, bad_client)
        # Status rolled back to 'open'.
        assert any("status='open'" in str(e[0]) for e in conn.executed)

    def test_close_yes_side_pnl_calculation(self) -> None:
        conn = FakeConn(
            close_claim=POSITION_ID,
            close_finalize=POSITION_ID,
        )
        s = _settings()
        client = MockClobClient()
        result = _run_close(conn, s, client)
        # Entry 0.6 → exit 0.8 on yes side: return = (0.8 - 0.6) / 0.6 ≈ 0.333
        assert result["pnl_usdc"] > Decimal("0")

    def test_close_no_side_pnl_calculation(self) -> None:
        no_position = {**_POSITION, "side": "no"}
        conn = FakeConn(
            close_claim=POSITION_ID,
            close_finalize=POSITION_ID,
        )
        s = _settings()
        client = MockClobClient()
        # No side: entry comp = 1-0.6 = 0.4, exit comp = 1-0.8 = 0.2
        # ret = (0.2 - 0.4) / 0.4 = -0.5 → loss
        result = _run_close(conn, s, client, position=no_position)
        assert result["pnl_usdc"] < Decimal("0")

    def test_close_clob_auth_error_during_construction_rolls_back_claim(self) -> None:
        """ClobAuthError from get_clob_client() during close → RuntimeError + rollback.

        Codex P1 finding (line 325): get_clob_client() can raise ClobAuthError
        during construction (malformed key) after the atomic claim has flipped
        the position to 'closing'. Previously only ClobConfigError was caught,
        so ClobAuthError escaped and left the position permanently stuck in
        'closing'; subsequent close attempts saw no 'open' row and returned
        'already_closed' without sending any broker SELL.
        """
        conn = FakeConn(close_claim=POSITION_ID, close_finalize=POSITION_ID)
        s = _settings()
        with (
            patch(
                "projects.polymarket.crusaderbot.domain.execution.live.get_clob_client",
                side_effect=ClobAuthError("malformed private key"),
            ),
            pytest.raises(RuntimeError, match="CLOB client error during close"),
        ):
            _run_close(conn, s, client=None)
        # Claim must be rolled back to 'open' so a retry can re-attempt.
        assert any("status='open'" in str(e[0]) for e in conn.executed)

    def test_close_raises_when_use_real_clob_false(self) -> None:
        """USE_REAL_CLOB=False → RuntimeError before atomic claim.

        Codex P1 (round 2): close_position intentionally skips assert_live_guards,
        so the USE_REAL_CLOB=False path must be caught here to prevent
        MockClobClient from phantom-closing a live position and crediting the
        ledger without submitting a real SELL to Polymarket.
        The check must fire BEFORE the atomic DB claim to leave the position
        in 'open' status for operator reconciliation.
        """
        conn = FakeConn(close_claim=POSITION_ID, close_finalize=POSITION_ID)
        s = _settings(use_real_clob=False)
        client = MockClobClient()
        with pytest.raises(RuntimeError, match="USE_REAL_CLOB=False"):
            _run_close(conn, s, client)
        # No DB fetchrow reached — position never touched.
        assert conn._call == 0
        assert client.open_orders() == []
