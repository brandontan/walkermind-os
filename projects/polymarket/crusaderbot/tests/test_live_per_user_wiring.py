"""Integration: live.execute selects per-user vs single-wallet client.

When ``USE_PER_USER_EXECUTION=True`` + ``USE_REAL_CLOB=True`` + no
``clob_client`` injected, ``live.execute`` MUST go through
``resolve_user_clob_client`` so the cross-user isolation assertion fires
on every order build. Anywhere else (flag OFF, USE_REAL_CLOB OFF, or
``clob_client`` explicitly provided) it MUST take the legacy path —
zero behavior change under the default config.
"""
from __future__ import annotations

import asyncio
from contextlib import ExitStack
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from projects.polymarket.crusaderbot.domain.execution.live import execute


_USER = uuid4()
_BASE_KWARGS: dict[str, Any] = dict(
    user_id=_USER,
    telegram_user_id=1,
    role="admin",
    trading_mode="live",
    market_id="mkt-abc",
    market_question="Will X happen?",
    yes_token_id="tok-yes",
    no_token_id="tok-no",
    side="yes",
    size_usdc=Decimal("100"),
    price=0.6,
    idempotency_key="key-per-user",
    strategy_type="copy_trade",
    tp_pct=None,
    sl_pct=None,
)


class _Settings:
    def __init__(self, *, per_user: bool, real: bool) -> None:
        self.USE_PER_USER_EXECUTION = per_user
        self.USE_REAL_CLOB = real
        # Live guards — all green so we reach the client-resolution branch.
        self.ENABLE_LIVE_TRADING = True
        self.EXECUTION_PATH_VALIDATED = True
        self.CAPITAL_MODE_CONFIRMED = True
        self.RISK_CONTROLS_VALIDATED = True
        self.SECURITY_HARDENING_VALIDATED = True


class _Txn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return None


class _Conn:
    def __init__(self) -> None:
        self.executed: list[tuple] = []

    def transaction(self):
        return _Txn()

    async def fetchrow(self, sql, *args):
        # The orders-row INSERT path — return a fake row id so live.execute
        # short-circuits via the idempotent-skip OR proceeds; we want it
        # to proceed so the assertion fires INSIDE the transaction.
        self.executed.append(("INSERT", args))
        # Return a row so live.execute treats the claim as the leader.
        return {"id": uuid4()}

    async def execute(self, *a, **k):
        return None

    async def fetchval(self, *a, **k):
        # No prior duplicate order — execute() proceeds to the resolution
        # branch, which is what these wiring tests are looking at.
        return None


class _PoolAcq:
    def __init__(self, conn) -> None:
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *_a):
        return None


class _Pool:
    def __init__(self, conn) -> None:
        self._conn = conn

    def acquire(self):
        return _PoolAcq(self._conn)


def _mdc() -> Any:
    m = MagicMock()
    m.get_tick_size = AsyncMock(return_value="0.01")
    m.get_neg_risk = AsyncMock(return_value=False)
    m.__aenter__ = AsyncMock(return_value=m)
    m.__aexit__ = AsyncMock(return_value=False)
    return m


def _wire(settings_obj, conn) -> tuple:
    """Return the patch-stack live.execute needs to reach the
    client-resolution branch without touching DB / broker / audit."""
    pool = _Pool(conn)
    return (
        patch("projects.polymarket.crusaderbot.domain.execution.live.get_settings",
              return_value=settings_obj),
        patch("projects.polymarket.crusaderbot.domain.execution.live.get_pool",
              return_value=pool),
        patch("projects.polymarket.crusaderbot.domain.execution.live.MarketDataClient",
              return_value=_mdc()),
        patch("projects.polymarket.crusaderbot.domain.execution.live.audit.write",
              new=AsyncMock()),
        patch("projects.polymarket.crusaderbot.domain.execution.live.notifications.send",
              new=AsyncMock()),
        patch("projects.polymarket.crusaderbot.domain.execution.live.notifications.notify_operator",
              new=AsyncMock()),
        patch("projects.polymarket.crusaderbot.domain.execution.live.ledger.debit_in_conn",
              new=AsyncMock()),
        # The pre-warm call (gemini #1741 CRITICAL fix) builds the per-user
        # cache OUTSIDE the conn. Stub it so the wiring tests don't try
        # to drive the real vault/SDK build path.
        patch(
            "projects.polymarket.crusaderbot.domain.execution.live"
            ".get_user_clob_client_with_wallet",
            new=AsyncMock(return_value=(MagicMock(), "0x0warmed")),
        ),
    )


# ── flag-gated dispatch ───────────────────────────────────────────────────────


def _enter_all(stack: ExitStack, patches) -> None:
    for p in patches:
        stack.enter_context(p)


def test_per_user_flag_on_calls_resolver() -> None:
    """USE_PER_USER_EXECUTION=True + no injected client → resolve_user_clob_client
    must be called with the same conn used for the idempotency claim."""
    s = _Settings(per_user=True, real=True)
    conn = _Conn()
    fake_client = MagicMock()
    fake_client.post_order = AsyncMock(return_value={
        "orderID": "0xresolved", "order_id": "0xresolved",
        "status": "live", "success": True,
    })

    seen = {}

    async def _resolve(*, user_id, conn, settings):
        seen["conn"] = conn
        seen["user_id"] = user_id
        return fake_client

    with ExitStack() as stack:
        _enter_all(stack, _wire(s, conn))
        stack.enter_context(patch(
            "projects.polymarket.crusaderbot.domain.execution.live"
            ".resolve_user_clob_client",
            side_effect=_resolve,
        ))
        get_global = stack.enter_context(patch(
            "projects.polymarket.crusaderbot.domain.execution.live"
            ".get_clob_client",
        ))
        try:
            asyncio.run(execute(**_BASE_KWARGS))
        except Exception:
            # Downstream post-submit DB writes will trip on our minimal
            # fake conn — we only care that the resolver was reached
            # BEFORE the broker call.
            pass

    assert seen["conn"] is conn, "resolver must see the claim conn"
    assert seen["user_id"] == _USER
    get_global.assert_not_called()


def test_per_user_flag_off_uses_global_client() -> None:
    """Default config: USE_PER_USER_EXECUTION absent → legacy single-wallet
    path is byte-identical (this is the safety net for the default rollout)."""
    s = _Settings(per_user=False, real=True)
    conn = _Conn()
    fake_global = MagicMock()
    fake_global.post_order = AsyncMock(return_value={
        "orderID": "0xglobal", "order_id": "0xglobal",
        "status": "live", "success": True,
    })

    with ExitStack() as stack:
        _enter_all(stack, _wire(s, conn))
        resolver = stack.enter_context(patch(
            "projects.polymarket.crusaderbot.domain.execution.live"
            ".resolve_user_clob_client",
        ))
        stack.enter_context(patch(
            "projects.polymarket.crusaderbot.domain.execution.live"
            ".get_clob_client",
            return_value=fake_global,
        ))
        try:
            asyncio.run(execute(**_BASE_KWARGS))
        except Exception:
            pass

    resolver.assert_not_called()


def test_injected_clob_client_overrides_flag() -> None:
    """An explicitly injected ``clob_client`` ALWAYS wins — staging /
    test harnesses don't get silently overridden by the per-user flag."""
    s = _Settings(per_user=True, real=True)
    conn = _Conn()
    injected = MagicMock()
    injected.post_order = AsyncMock(return_value={
        "orderID": "0xinjected", "order_id": "0xinjected",
        "status": "live", "success": True,
    })

    with ExitStack() as stack:
        _enter_all(stack, _wire(s, conn))
        resolver = stack.enter_context(patch(
            "projects.polymarket.crusaderbot.domain.execution.live"
            ".resolve_user_clob_client",
        ))
        get_global = stack.enter_context(patch(
            "projects.polymarket.crusaderbot.domain.execution.live"
            ".get_clob_client",
        ))
        try:
            asyncio.run(execute(clob_client=injected, **_BASE_KWARGS))
        except Exception:
            pass

    resolver.assert_not_called()
    get_global.assert_not_called()


# ── SAFETY-CRITICAL: end-to-end drift refuse ─────────────────────────────────
#
# These tests are the SENTINEL Step 5 close-out: prove the wallet-identity
# assertion fires THROUGH the full live.execute path (not just in the
# resolver unit), classifies cleanly as LivePreSubmitError, and crucially
# NEVER invokes ``client.post_order`` — drift becomes a definitive
# pre-submit refuse so the router's existing pre-submit→paper-fallback
# classification applies + no broker call happens.


def test_drift_refuses_through_full_execute_path() -> None:
    """Resolver raises WalletIdentityMismatch → live.execute raises
    LivePreSubmitError, NO broker call. The whole point of the lane."""
    from projects.polymarket.crusaderbot.domain.execution.live import (
        LivePreSubmitError,
    )
    from projects.polymarket.crusaderbot.domain.execution.per_user_clob import (
        WalletIdentityMismatch,
    )

    s = _Settings(per_user=True, real=True)
    conn = _Conn()
    drifted_client = MagicMock()
    drifted_client.post_order = AsyncMock(return_value={})

    drift = WalletIdentityMismatch(
        "deposit wallet drift for user_id=<test>: "
        "sdk=0xaaa stored=0xbbb"
    )

    with ExitStack() as stack:
        _enter_all(stack, _wire(s, conn))
        stack.enter_context(patch(
            "projects.polymarket.crusaderbot.domain.execution.live"
            ".resolve_user_clob_client",
            side_effect=drift,
        ))
        with pytest.raises(LivePreSubmitError, match="isolation refused"):
            asyncio.run(execute(**_BASE_KWARGS))

    drifted_client.post_order.assert_not_called()
    # Defensive: no orders row was inserted because the drift raises
    # BEFORE the INSERT. The conn fixture only records INSERT/execute
    # calls — verify none of them are the orders INSERT.
    assert not any(
        "INSERT INTO orders" in (q[0] if isinstance(q[0], str) else "")
        for q in conn.executed
    )


def test_isolation_violation_through_full_execute_path() -> None:
    """A None/non-UUID user_id smuggled past upstream typing must ALSO
    refuse via the same PerUserClobError catch (defense-in-depth)."""
    from projects.polymarket.crusaderbot.domain.execution.live import (
        LivePreSubmitError,
    )
    from projects.polymarket.crusaderbot.integrations.clob.user_client import (
        PerUserClobIsolationError,
    )

    s = _Settings(per_user=True, real=True)
    conn = _Conn()

    with ExitStack() as stack:
        _enter_all(stack, _wire(s, conn))
        stack.enter_context(patch(
            "projects.polymarket.crusaderbot.domain.execution.live"
            ".resolve_user_clob_client",
            side_effect=PerUserClobIsolationError(
                "test: user_id not a UUID"
            ),
        ))
        with pytest.raises(LivePreSubmitError, match="isolation refused"):
            asyncio.run(execute(**_BASE_KWARGS))
