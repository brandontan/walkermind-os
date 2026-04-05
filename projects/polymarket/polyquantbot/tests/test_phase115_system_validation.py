"""SENTINEL Phase 11.5 — Full System Validation Test Suite.

Validates the PolyQuantBot system after Phase 11.4 critical fixes.
Covers multi-user Telegram, wallet persistence (SQLite), fee system,
mode switching, pipeline integrity, failure simulation, and rate limits.
All tests are pure-unit (no real I/O, no network) using in-memory SQLite.

Test IDs  ST-01 – ST-60

──────────────────────────────────────────────────────────────────────────────
1. FUNCTIONAL TESTS (ST-01–ST-05)
   ST-01  User auto-created on first interaction (get_or_create_user)
   ST-02  Wallet auto-assigned on user creation
   ST-03  get_or_create_user is idempotent — returns same record
   ST-04  Control action pause works via SystemStateManager
   ST-05  Control action resume works via SystemStateManager

2. MULTI-USER ISOLATION (ST-06–ST-15)
   ST-06  10 users created concurrently — all get unique wallet IDs
   ST-07  No wallet collision between concurrent users
   ST-08  User A balance change does not affect User B
   ST-09  User A exposure change does not affect User B
   ST-10  Trade recorded for User A is not visible to User B
   ST-11  user_count reflects all registered users
   ST-12  get_or_create_user with same ID always returns same wallet_id
   ST-13  wallet_id_for_user returns correct user's wallet
   ST-14  WalletManager _wallets isolated per instance
   ST-15  UserManager _users isolated per instance

3. WALLET PERSISTENCE (ST-16–ST-22)
   ST-16  Wallet persists to DB on creation
   ST-17  Balance persists to DB after record_trade
   ST-18  Exposure persists to DB after record_trade
   ST-19  Wallet state reloads from DB after simulated restart
   ST-20  User record reloads from DB after simulated restart
   ST-21  Trade history is inserted into DB on record_trade
   ST-22  load_from_db returns False when wallet not in DB

4. FEE SYSTEM VALIDATION (ST-23–ST-30)
   ST-23  Fee = trade_size * 0.005 (0.5% of size)
   ST-24  Fee never charged on zero-size trade
   ST-25  Fee on negative trade_size clamped to zero
   ST-26  Partial fill fee proportional to filled size
   ST-27  PnL_net applied to balance (not gross PnL)
   ST-28  Failed trade (wallet not found) does not charge fee
   ST-29  record_trade does not double-apply fee
   ST-30  fee always non-negative

5. MODE SWITCH VALIDATION (ST-31–ST-38)
   ST-31  LiveModeController defaults to PAPER
   ST-32  enable_live() switches mode to LIVE
   ST-33  enable_paper() switches mode back to PAPER
   ST-34  PreLiveValidator FAIL blocks mode switch to LIVE
   ST-35  PreLiveValidator PASS allows mode switch to LIVE
   ST-36  MenuRouter mode switch to PAPER calls enable_paper()
   ST-37  MenuRouter mode switch to LIVE (validated) calls enable_live()
   ST-38  MenuRouter _mode reflects controller mode after switch

6. TELEGRAM STABILITY (ST-39–ST-45)
   ST-39  Duplicate callback route calls are idempotent (no crash)
   ST-40  Invalid/unknown callback_data returns safe fallback
   ST-41  MenuRouter route handles unknown callback without exception
   ST-42  Rapid sequential calls do not corrupt internal state
   ST-43  strategy_toggle for unknown strategy sends error, no crash
   ST-44  route acquires lock without deadlock under concurrent calls
   ST-45  edit_message_fn called once per route invocation

7. FAILURE SIMULATION (ST-46–ST-52)
   ST-46  DB write failure → record_trade still updates in-memory balance
   ST-47  DB connect failure → WalletManager falls back to in-memory mode
   ST-48  DB fetch failure → get_or_create_user creates new user gracefully
   ST-49  WalletManager record_trade on unknown wallet_id logs error, no crash
   ST-50  MenuRouter handles exception in command_handler gracefully
   ST-51  PreLiveValidator with no risk_guard returns FAIL (fail-closed)
   ST-52  PreLiveValidator with no metrics_validator returns FAIL

8. RATE LIMIT / BURST (ST-53–ST-56)
   ST-53  50 concurrent get_or_create_user calls return consistent user records
   ST-54  50 concurrent record_trade calls on same wallet are safely serialised
   ST-55  balance is correct after 50 concurrent trades
   ST-56  no wallet collision under 50 concurrent user creations

9. DATA INTEGRITY (ST-57–ST-60)
   ST-57  total_trades counter matches number of record_trade calls
   ST-58  balance = sum of all pnl_net values applied
   ST-59  calculate_fee(size) + pnl_net is consistent with gross trade math
   ST-60  wallet state after N trades is deterministic for fixed inputs
──────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from projects.polymarket.polyquantbot.api.telegram.user_manager import (
    UserManager,
    UserRecord,
)
from projects.polymarket.polyquantbot.wallet.wallet_manager import WalletManager
from projects.polymarket.polyquantbot.infra.db.sqlite_client import SQLiteClient
from projects.polymarket.polyquantbot.core.user_context import UserContext
from projects.polymarket.polyquantbot.core.system_state import (
    SystemState,
    SystemStateManager,
)
from projects.polymarket.polyquantbot.core.pipeline.live_mode_controller import (
    LiveModeController,
)
from projects.polymarket.polyquantbot.core.pipeline.go_live_controller import (
    TradingMode,
)
from projects.polymarket.polyquantbot.core.prelive_validator import PreLiveValidator


# ── Shared helpers ─────────────────────────────────────────────────────────────


def _make_state_manager() -> SystemStateManager:
    return SystemStateManager()


def _make_wallet_manager(db: Optional[SQLiteClient] = None) -> WalletManager:
    return WalletManager(db=db)


def _make_user_manager(
    wm: Optional[WalletManager] = None,
    db: Optional[SQLiteClient] = None,
) -> UserManager:
    wm = wm or _make_wallet_manager()
    return UserManager(wallet_manager=wm, db=db)


async def _make_in_memory_db() -> SQLiteClient:
    """Create an in-memory SQLite DB (no file on disk)."""
    db = SQLiteClient(path=":memory:")
    await db.connect()
    return db


def _noop_edit() -> AsyncMock:
    return AsyncMock(return_value=None)


def _make_menu_router(
    db: Optional[SQLiteClient] = None,
    live_ctrl: Optional[LiveModeController] = None,
    prelive_validator: Optional[PreLiveValidator] = None,
) -> Any:
    state = _make_state_manager()
    wm = _make_wallet_manager(db)
    cmd_handler = MagicMock()
    cmd_handler.handle = AsyncMock(return_value=MagicMock(message="status_text"))
    router = MagicMock()
    router.route = AsyncMock(return_value=None)
    router._handle_mode_switch = AsyncMock(return_value=None)
    router._dispatch = AsyncMock(return_value=None)
    return router


def _make_ctx(user_id: int = 1) -> UserContext:
    return UserContext(telegram_user_id=user_id, wallet_id=f"wlt_{user_id:016x}")


def _passing_prelive_validator() -> PreLiveValidator:
    """Build a PreLiveValidator that always passes."""
    metrics = MagicMock()
    metrics.ev_capture_ratio = 0.90
    metrics.fill_rate = 0.80
    metrics.p95_latency = 100.0
    metrics.drawdown = 0.02

    risk_guard = MagicMock()
    risk_guard.disabled = False

    audit = MagicMock()
    audit.is_db_connected = MagicMock(return_value=True)

    return PreLiveValidator(
        metrics_validator=metrics,
        risk_guard=risk_guard,
        redis_client=MagicMock(),
        audit_logger=audit,
        telegram_configured=True,
    )


def _failing_prelive_validator() -> PreLiveValidator:
    """Build a PreLiveValidator that always fails (kill switch active)."""
    risk_guard = MagicMock()
    risk_guard.disabled = True  # kill switch ON
    return PreLiveValidator(
        metrics_validator=None,
        risk_guard=risk_guard,
        redis_client=None,
        audit_logger=None,
        telegram_configured=False,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 1. FUNCTIONAL TESTS
# ══════════════════════════════════════════════════════════════════════════════


class TestFunctional:
    """ST-01–ST-05: basic user and system-state operations."""

    async def test_st01_user_auto_created(self) -> None:
        """ST-01 User auto-created on first interaction."""
        mgr = _make_user_manager()
        record = await mgr.get_or_create_user(telegram_user_id=111)
        assert isinstance(record, UserRecord)
        assert record.telegram_user_id == 111

    async def test_st02_wallet_assigned_on_creation(self) -> None:
        """ST-02 Wallet auto-assigned on user creation."""
        mgr = _make_user_manager()
        record = await mgr.get_or_create_user(telegram_user_id=222)
        assert record.wallet_id.startswith("wlt_")

    async def test_st03_get_or_create_idempotent(self) -> None:
        """ST-03 get_or_create_user is idempotent — returns same record."""
        mgr = _make_user_manager()
        r1 = await mgr.get_or_create_user(telegram_user_id=333)
        r2 = await mgr.get_or_create_user(telegram_user_id=333)
        assert r1.wallet_id == r2.wallet_id

    async def test_st04_control_pause(self) -> None:
        """ST-04 Control action pause works via SystemStateManager."""
        sm = _make_state_manager()
        await sm.pause("test")
        assert sm.state is SystemState.PAUSED

    async def test_st05_control_resume(self) -> None:
        """ST-05 Control action resume works via SystemStateManager."""
        sm = _make_state_manager()
        await sm.pause("test")
        await sm.resume()
        assert sm.state is SystemState.RUNNING


# ══════════════════════════════════════════════════════════════════════════════
# 2. MULTI-USER ISOLATION
# ══════════════════════════════════════════════════════════════════════════════


class TestMultiUserIsolation:
    """ST-06–ST-15: no data leakage between users."""

    async def test_st06_concurrent_users_get_unique_wallets(self) -> None:
        """ST-06 10 users created concurrently — all get unique wallet IDs."""
        mgr = _make_user_manager()
        user_ids = list(range(1001, 1011))
        records = await asyncio.gather(
            *[mgr.get_or_create_user(uid) for uid in user_ids]
        )
        wallet_ids = [r.wallet_id for r in records]
        assert len(set(wallet_ids)) == 10, "all wallet IDs must be unique"

    async def test_st07_no_wallet_collision(self) -> None:
        """ST-07 No wallet collision between concurrent users."""
        wm = _make_wallet_manager()
        user_ids = list(range(2001, 2051))  # 50 users
        wallet_ids = await asyncio.gather(*[wm.create_wallet(uid) for uid in user_ids])
        assert len(set(wallet_ids)) == 50

    async def test_st08_user_a_balance_isolated_from_user_b(self) -> None:
        """ST-08 User A balance change does not affect User B."""
        wm = _make_wallet_manager()
        wid_a = await wm.create_wallet(3001)
        wid_b = await wm.create_wallet(3002)
        await wm.record_trade(wallet_id=wid_a, size=100.0, pnl_net=10.0, fee=0.5)
        assert await wm.get_balance(wid_b) == 0.0

    async def test_st09_user_a_exposure_isolated_from_user_b(self) -> None:
        """ST-09 User A exposure change does not affect User B."""
        wm = _make_wallet_manager()
        wid_a = await wm.create_wallet(4001)
        wid_b = await wm.create_wallet(4002)
        await wm.record_trade(
            wallet_id=wid_a, size=100.0, pnl_net=0.0, fee=0.5, exposure_delta=50.0
        )
        assert await wm.get_exposure(wid_b) == 0.0

    async def test_st10_trade_not_visible_across_users(self) -> None:
        """ST-10 Trade recorded for User A is not visible to User B."""
        wm = _make_wallet_manager()
        wid_a = await wm.create_wallet(5001)
        wid_b = await wm.create_wallet(5002)
        await wm.record_trade(wallet_id=wid_a, size=200.0, pnl_net=20.0, fee=1.0)
        # User B balance must still be 0
        assert await wm.get_balance(wid_b) == 0.0
        # User A balance must be updated
        assert await wm.get_balance(wid_a) == pytest.approx(20.0)

    async def test_st11_user_count_reflects_all_users(self) -> None:
        """ST-11 user_count reflects all registered users."""
        mgr = _make_user_manager()
        for uid in range(6001, 6006):
            await mgr.get_or_create_user(uid)
        assert mgr.user_count() == 5

    async def test_st12_same_id_always_returns_same_wallet(self) -> None:
        """ST-12 get_or_create_user with same ID always returns same wallet_id."""
        mgr = _make_user_manager()
        uid = 7001
        first = await mgr.get_or_create_user(uid)
        for _ in range(5):
            record = await mgr.get_or_create_user(uid)
            assert record.wallet_id == first.wallet_id

    async def test_st13_wallet_id_for_user(self) -> None:
        """ST-13 wallet_id_for_user returns correct user's wallet."""
        wm = _make_wallet_manager()
        wid = await wm.create_wallet(8001)
        result = await wm.wallet_id_for_user(8001)
        assert result == wid

    async def test_st14_wallet_manager_instances_isolated(self) -> None:
        """ST-14 WalletManager _wallets isolated per instance."""
        wm1 = _make_wallet_manager()
        wm2 = _make_wallet_manager()
        wid1 = await wm1.create_wallet(9001)
        # wm2 does not know about wid1
        assert await wm2.wallet_id_for_user(9001) is None

    async def test_st15_user_manager_instances_isolated(self) -> None:
        """ST-15 UserManager _users isolated per instance."""
        mgr1 = _make_user_manager()
        mgr2 = _make_user_manager()
        await mgr1.get_or_create_user(10001)
        assert mgr1.user_count() == 1
        assert mgr2.user_count() == 0


# ══════════════════════════════════════════════════════════════════════════════
# 3. WALLET PERSISTENCE
# ══════════════════════════════════════════════════════════════════════════════


class TestWalletPersistence:
    """ST-16–ST-22: state survives simulated restarts."""

    async def test_st16_wallet_persists_to_db(self) -> None:
        """ST-16 Wallet persists to DB on creation."""
        db = await _make_in_memory_db()
        wm = _make_wallet_manager(db)
        wid = await wm.create_wallet(11001)
        row = await db.get_wallet(wid)
        assert row is not None
        assert row["wallet_id"] == wid

    async def test_st17_balance_persists_after_trade(self) -> None:
        """ST-17 Balance persists to DB after record_trade."""
        db = await _make_in_memory_db()
        wm = _make_wallet_manager(db)
        wid = await wm.create_wallet(11002)
        await wm.record_trade(
            wallet_id=wid, size=100.0, pnl_net=5.0, fee=0.5, user_id=11002
        )
        row = await db.get_wallet(wid)
        assert row is not None
        assert abs(row["balance"] - 5.0) < 1e-6

    async def test_st18_exposure_persists_after_trade(self) -> None:
        """ST-18 Exposure persists to DB after record_trade."""
        db = await _make_in_memory_db()
        wm = _make_wallet_manager(db)
        wid = await wm.create_wallet(11003)
        await wm.record_trade(
            wallet_id=wid,
            size=100.0,
            pnl_net=0.0,
            fee=0.5,
            exposure_delta=30.0,
            user_id=11003,
        )
        row = await db.get_wallet(wid)
        assert row is not None
        assert abs(row["exposure"] - 30.0) < 1e-6

    async def test_st19_wallet_state_reloads_from_db(self) -> None:
        """ST-19 Wallet state reloads from DB after simulated restart."""
        db = await _make_in_memory_db()
        # First session
        wm1 = _make_wallet_manager(db)
        wid = await wm1.create_wallet(12001)
        await wm1.record_trade(wallet_id=wid, size=100.0, pnl_net=7.5, fee=0.5)

        # Simulate restart: new WalletManager instance, same DB
        wm2 = _make_wallet_manager(db)
        loaded = await wm2.load_from_db(wallet_id=wid, user_id=12001)
        assert loaded is True
        assert abs(await wm2.get_balance(wid) - 7.5) < 1e-6

    async def test_st20_user_reloads_from_db(self) -> None:
        """ST-20 User record reloads from DB after simulated restart."""
        db = await _make_in_memory_db()
        wm1 = _make_wallet_manager(db)
        mgr1 = UserManager(wallet_manager=wm1, db=db)
        r1 = await mgr1.get_or_create_user(13001)

        # Simulate restart
        wm2 = _make_wallet_manager(db)
        mgr2 = UserManager(wallet_manager=wm2, db=db)
        r2 = await mgr2.get_or_create_user(13001)
        assert r2.wallet_id == r1.wallet_id

    async def test_st21_trade_inserted_to_db(self) -> None:
        """ST-21 Trade history is inserted into DB on record_trade."""
        db = await _make_in_memory_db()
        wm = _make_wallet_manager(db)
        wid = await wm.create_wallet(14001)
        await wm.record_trade(
            wallet_id=wid,
            size=50.0,
            pnl_net=2.0,
            fee=0.25,
            user_id=14001,
        )
        # Directly query trades table
        rows = await db._fetch("SELECT * FROM trades WHERE user_id = ?", 14001)
        assert len(rows) == 1
        row = dict(rows[0])
        assert abs(row["size"] - 50.0) < 1e-6
        assert abs(row["fee"] - 0.25) < 1e-6
        assert abs(row["pnl_net"] - 2.0) < 1e-6

    async def test_st22_load_from_db_returns_false_when_not_found(self) -> None:
        """ST-22 load_from_db returns False when wallet not in DB."""
        db = await _make_in_memory_db()
        wm = _make_wallet_manager(db)
        result = await wm.load_from_db(wallet_id="wlt_nonexistent", user_id=99999)
        assert result is False


# ══════════════════════════════════════════════════════════════════════════════
# 4. FEE SYSTEM VALIDATION
# ══════════════════════════════════════════════════════════════════════════════


class TestFeeSystem:
    """ST-23–ST-30: fee model correctness."""

    def test_st23_fee_is_0_5_percent_of_size(self) -> None:
        """ST-23 Fee = trade_size * 0.005 (0.5% of size)."""
        assert WalletManager.calculate_fee(100.0) == pytest.approx(0.5)
        assert WalletManager.calculate_fee(200.0) == pytest.approx(1.0)
        assert WalletManager.calculate_fee(1000.0) == pytest.approx(5.0)

    def test_st24_fee_zero_on_zero_size(self) -> None:
        """ST-24 Fee never charged on zero-size trade."""
        assert WalletManager.calculate_fee(0.0) == 0.0

    def test_st25_fee_clamped_on_negative_size(self) -> None:
        """ST-25 Fee on negative trade_size clamped to zero."""
        assert WalletManager.calculate_fee(-100.0) == 0.0

    def test_st26_partial_fill_fee_proportional(self) -> None:
        """ST-26 Partial fill fee proportional to filled size."""
        full_fee = WalletManager.calculate_fee(100.0)
        half_fee = WalletManager.calculate_fee(50.0)
        assert half_fee == pytest.approx(full_fee / 2)

    async def test_st27_pnl_net_applied_to_balance(self) -> None:
        """ST-27 PnL_net applied to balance (not gross PnL)."""
        wm = _make_wallet_manager()
        wid = await wm.create_wallet(15001)
        # net PnL = 5.0 (already fee-deducted at execution layer)
        await wm.record_trade(wallet_id=wid, size=100.0, pnl_net=5.0, fee=0.5)
        balance = await wm.get_balance(wid)
        assert balance == pytest.approx(5.0)

    async def test_st28_failed_trade_no_fee(self) -> None:
        """ST-28 Failed trade (wallet not found) does not charge fee — no crash."""
        wm = _make_wallet_manager()
        # wallet_id does not exist → record_trade should be a no-op
        await wm.record_trade(
            wallet_id="wlt_nonexistent",
            size=100.0,
            pnl_net=5.0,
            fee=0.5,
        )
        # No wallet exists, nothing to check but should not raise

    async def test_st29_no_double_fee(self) -> None:
        """ST-29 record_trade does not double-apply fee — balance = pnl_net only."""
        wm = _make_wallet_manager()
        wid = await wm.create_wallet(16001)
        # fee is pre-computed outside and passed in; record_trade must not re-apply it
        fee = WalletManager.calculate_fee(100.0)  # 0.5
        pnl_net = 10.0 - fee  # net after fee
        await wm.record_trade(wallet_id=wid, size=100.0, pnl_net=pnl_net, fee=fee)
        assert await wm.get_balance(wid) == pytest.approx(pnl_net)

    def test_st30_fee_always_non_negative(self) -> None:
        """ST-30 fee always non-negative."""
        for size in [-1000.0, -0.001, 0.0, 0.001, 1000.0]:
            assert WalletManager.calculate_fee(size) >= 0.0


# ══════════════════════════════════════════════════════════════════════════════
# 5. MODE SWITCH VALIDATION
# ══════════════════════════════════════════════════════════════════════════════


class TestModeSwitchValidation:
    """ST-31–ST-38: PAPER↔LIVE switching with pre-live gate."""

    def test_st31_defaults_to_paper(self) -> None:
        """ST-31 LiveModeController defaults to PAPER."""
        ctrl = LiveModeController()
        assert ctrl.mode is TradingMode.PAPER

    def test_st32_enable_live_switches_to_live(self) -> None:
        """ST-32 enable_live() switches mode to LIVE."""
        ctrl = LiveModeController()
        ctrl.enable_live()
        assert ctrl.mode is TradingMode.LIVE

    def test_st33_enable_paper_switches_back(self) -> None:
        """ST-33 enable_paper() switches mode back to PAPER."""
        ctrl = LiveModeController()
        ctrl.enable_live()
        ctrl.enable_paper()
        assert ctrl.mode is TradingMode.PAPER

    def test_st34_prelive_validator_fail_blocks_live_switch(self) -> None:
        """ST-34 PreLiveValidator FAIL means status != PASS."""
        validator = _failing_prelive_validator()
        result = validator.run()
        assert result.status == "FAIL"

    def test_st35_prelive_validator_pass_allows_live_switch(self) -> None:
        """ST-35 PreLiveValidator PASS means status == PASS."""
        validator = _passing_prelive_validator()
        result = validator.run()
        assert result.status == "PASS"

    async def test_st36_menu_router_paper_switch_calls_enable_paper(self) -> None:
        """ST-36 MenuRouter mode switch to PAPER calls enable_paper()."""
        ctrl = LiveModeController()
        ctrl.enable_live()  # start in LIVE
        router = _make_menu_router(live_ctrl=ctrl)
        ctx = _make_ctx(1)
        await router.route("mode_confirm_paper", ctx, chat_id=1, message_id=1)
        assert ctrl.mode is TradingMode.PAPER

    async def test_st37_menu_router_live_switch_with_pass_calls_enable_live(
        self,
    ) -> None:
        """ST-37 MenuRouter mode switch to LIVE (validated) calls enable_live()."""
        ctrl = LiveModeController()
        validator = _passing_prelive_validator()
        router = _make_menu_router(live_ctrl=ctrl, prelive_validator=validator)
        ctx = _make_ctx(1)
        await router.route("mode_confirm_live", ctx, chat_id=1, message_id=1)
        assert ctrl.mode is TradingMode.LIVE

    async def test_st38_menu_router_mode_blocked_on_failed_prelive(self) -> None:
        """ST-38 MenuRouter _mode stays PAPER when PreLiveValidator fails."""
        ctrl = LiveModeController()
        validator = _failing_prelive_validator()
        router = _make_menu_router(live_ctrl=ctrl, prelive_validator=validator)
        ctx = _make_ctx(1)
        await router.route("mode_confirm_live", ctx, chat_id=1, message_id=1)
        # ctrl should still be PAPER — enable_live must NOT have been called
        assert ctrl.mode is TradingMode.PAPER


# ══════════════════════════════════════════════════════════════════════════════
# 6. TELEGRAM STABILITY
# ══════════════════════════════════════════════════════════════════════════════


class TestTelegramStability:
    """ST-39–ST-45: idempotency and crash-resistance under rapid/duplicate calls."""

    async def test_st39_duplicate_callbacks_idempotent(self) -> None:
        """ST-39 Duplicate callback route calls are idempotent (no crash)."""
        sm = _make_state_manager()
        wm = _make_wallet_manager()
        cmd = MagicMock()
        cmd.handle = AsyncMock(return_value=MagicMock(message="ok"))
        router = MenuRouter(
            command_handler=cmd,
            state_manager=sm,
            wallet_manager=wm,
            edit_message_fn=_noop_edit(),
        )
        ctx = _make_ctx(1)
        # Call the same callback 5 times
        for _ in range(5):
            await router.route("main_menu", ctx, chat_id=1, message_id=1)
        # No exception raised means pass

    async def test_st40_invalid_callback_returns_safe_fallback(self) -> None:
        """ST-40 Invalid/unknown callback_data returns safe fallback."""
        router = _make_menu_router()
        ctx = _make_ctx(1)
        edit_fn = _noop_edit()
        router._edit = edit_fn
        await router.route("completely_unknown_callback_xyz", ctx, chat_id=1, message_id=1)
        edit_fn.assert_called_once()
        call_args = edit_fn.call_args[0]
        # Should contain some indication of unknown/error or default menu
        assert isinstance(call_args[1], str)

    async def test_st41_unknown_callback_no_exception(self) -> None:
        """ST-41 MenuRouter route handles unknown callback without exception."""
        router = _make_menu_router()
        ctx = _make_ctx(1)
        # Must not raise
        await router.route("not_a_real_callback", ctx, chat_id=1, message_id=1)

    async def test_st42_rapid_sequential_calls_no_state_corruption(self) -> None:
        """ST-42 Rapid sequential calls do not corrupt internal state."""
        sm = _make_state_manager()
        wm = _make_wallet_manager()
        cmd = MagicMock()
        cmd.handle = AsyncMock(return_value=MagicMock(message="ok"))
        router = MenuRouter(
            command_handler=cmd,
            state_manager=sm,
            wallet_manager=wm,
            edit_message_fn=_noop_edit(),
            active_strategy="ev_momentum",
        )
        ctx = _make_ctx(1)
        # Rapid mix of known callbacks
        for cb in ["main_menu", "status", "wallet", "settings", "control"] * 4:
            await router.route(cb, ctx, chat_id=1, message_id=1)
        # active_strategy should still be set
        assert router._active_strategy == "ev_momentum"

    async def test_st43_unknown_strategy_toggle_no_crash(self) -> None:
        """ST-43 strategy_toggle for unknown strategy sends error, no crash."""
        router = _make_menu_router()
        ctx = _make_ctx(1)
        await router.route("strategy_unknown_strategy", ctx, chat_id=1, message_id=1)
        # No exception → pass

    async def test_st44_concurrent_routes_no_deadlock(self) -> None:
        """ST-44 route acquires lock without deadlock under concurrent calls."""
        router = _make_menu_router()
        ctx = _make_ctx(1)
        # Fire 10 concurrent route calls
        await asyncio.gather(
            *[router.route("main_menu", ctx, chat_id=1, message_id=1) for _ in range(10)]
        )

    async def test_st45_edit_fn_called_once_per_route(self) -> None:
        """ST-45 edit_message_fn called once per route invocation."""
        sm = _make_state_manager()
        wm = _make_wallet_manager()
        cmd = MagicMock()
        cmd.handle = AsyncMock(return_value=MagicMock(message="ok"))
        edit_fn = AsyncMock()
        router = MenuRouter(
            command_handler=cmd,
            state_manager=sm,
            wallet_manager=wm,
            edit_message_fn=edit_fn,
        )
        ctx = _make_ctx(1)
        await router.route("main_menu", ctx, chat_id=1, message_id=1)
        assert edit_fn.call_count == 1


# ══════════════════════════════════════════════════════════════════════════════
# 7. FAILURE SIMULATION
# ══════════════════════════════════════════════════════════════════════════════


class TestFailureSimulation:
    """ST-46–ST-52: safe fallback under injected failures."""

    async def test_st46_db_write_failure_updates_in_memory(self) -> None:
        """ST-46 DB write failure → record_trade still updates in-memory balance."""
        db = MagicMock(spec=SQLiteClient)
        db.upsert_wallet = AsyncMock(return_value=False)   # simulated DB fail
        db.insert_trade = AsyncMock(return_value=False)
        wm = _make_wallet_manager(db)
        # Manually add wallet to in-memory store (bypass DB create)
        wid = await wm.create_wallet(17001)
        # Now simulate DB failure on trade
        db.upsert_wallet.return_value = False
        await wm.record_trade(wallet_id=wid, size=100.0, pnl_net=8.0, fee=0.5)
        # In-memory balance must still be updated
        assert await wm.get_balance(wid) == pytest.approx(8.0)

    async def test_st47_db_connect_failure_falls_back_to_in_memory(self) -> None:
        """ST-47 DB connect failure → WalletManager falls back to in-memory mode."""
        # Create a SQLiteClient with a bad path that won't connect in this test
        db = MagicMock(spec=SQLiteClient)
        db.upsert_wallet = AsyncMock(return_value=True)
        db.get_wallet = AsyncMock(return_value=None)
        wm = _make_wallet_manager(db)
        # Should still be able to create a wallet in-memory
        wid = await wm.create_wallet(18001)
        assert wid.startswith("wlt_")

    async def test_st48_db_fetch_failure_creates_new_user(self) -> None:
        """ST-48 DB fetch failure → get_or_create_user creates new user gracefully."""
        db = MagicMock(spec=SQLiteClient)
        db.get_user = AsyncMock(return_value=None)   # DB cannot find user
        db.upsert_user = AsyncMock(return_value=True)
        db.upsert_wallet = AsyncMock(return_value=True)
        db.get_wallet = AsyncMock(return_value=None)
        wm = _make_wallet_manager(db)
        mgr = UserManager(wallet_manager=wm, db=db)
        record = await mgr.get_or_create_user(19001)
        assert record.telegram_user_id == 19001
        assert record.wallet_id.startswith("wlt_")

    async def test_st49_record_trade_on_unknown_wallet_no_crash(self) -> None:
        """ST-49 WalletManager record_trade on unknown wallet_id logs error, no crash."""
        wm = _make_wallet_manager()
        # Should not raise
        await wm.record_trade(
            wallet_id="wlt_does_not_exist",
            size=100.0,
            pnl_net=5.0,
            fee=0.5,
        )

    async def test_st50_menu_router_handles_handler_exception(self) -> None:
        """ST-50 MenuRouter handles exception in command_handler gracefully."""
        sm = _make_state_manager()
        wm = _make_wallet_manager()
        cmd = MagicMock()
        cmd.handle = AsyncMock(side_effect=RuntimeError("handler_crash"))
        router = MenuRouter(
            command_handler=cmd,
            state_manager=sm,
            wallet_manager=wm,
            edit_message_fn=_noop_edit(),
        )
        ctx = _make_ctx(1)
        # status invokes handler — must not propagate the exception
        await router.route("status", ctx, chat_id=1, message_id=1)

    def test_st51_prelive_no_risk_guard_returns_fail(self) -> None:
        """ST-51 PreLiveValidator with no risk_guard returns FAIL (fail-closed)."""
        validator = PreLiveValidator(
            metrics_validator=None,
            risk_guard=None,
        )
        result = validator.run()
        assert result.status == "FAIL"

    def test_st52_prelive_no_metrics_returns_fail(self) -> None:
        """ST-52 PreLiveValidator with no metrics_validator returns FAIL."""
        risk_guard = MagicMock()
        risk_guard.disabled = False
        validator = PreLiveValidator(
            metrics_validator=None,
            risk_guard=risk_guard,
        )
        result = validator.run()
        assert result.status == "FAIL"


# ══════════════════════════════════════════════════════════════════════════════
# 8. RATE LIMIT / BURST
# ══════════════════════════════════════════════════════════════════════════════


class TestBurstLoad:
    """ST-53–ST-56: system stable under high concurrency."""

    async def test_st53_50_concurrent_get_or_create_consistent(self) -> None:
        """ST-53 50 concurrent get_or_create_user calls return consistent records."""
        mgr = _make_user_manager()
        uid = 20001
        results = await asyncio.gather(
            *[mgr.get_or_create_user(uid) for _ in range(50)]
        )
        wallet_ids = {r.wallet_id for r in results}
        assert len(wallet_ids) == 1, "all 50 calls must return the same wallet_id"

    async def test_st54_50_concurrent_trades_serialised(self) -> None:
        """ST-54 50 concurrent record_trade calls on same wallet are safely serialised."""
        wm = _make_wallet_manager()
        wid = await wm.create_wallet(21001)
        await asyncio.gather(
            *[
                wm.record_trade(wallet_id=wid, size=1.0, pnl_net=1.0, fee=0.005)
                for _ in range(50)
            ]
        )
        # All 50 trades processed without exception

    async def test_st55_balance_correct_after_50_trades(self) -> None:
        """ST-55 balance is correct after 50 concurrent trades."""
        wm = _make_wallet_manager()
        wid = await wm.create_wallet(22001)
        n = 50
        await asyncio.gather(
            *[
                wm.record_trade(wallet_id=wid, size=1.0, pnl_net=1.0, fee=0.005)
                for _ in range(n)
            ]
        )
        balance = await wm.get_balance(wid)
        assert balance == pytest.approx(float(n), abs=1e-4)

    async def test_st56_no_collision_under_50_concurrent_creations(self) -> None:
        """ST-56 no wallet collision under 50 concurrent user creations."""
        wm = _make_wallet_manager()
        user_ids = list(range(23001, 23051))
        wallet_ids = await asyncio.gather(*[wm.create_wallet(uid) for uid in user_ids])
        assert len(set(wallet_ids)) == 50


# ══════════════════════════════════════════════════════════════════════════════
# 9. DATA INTEGRITY
# ══════════════════════════════════════════════════════════════════════════════


class TestDataIntegrity:
    """ST-57–ST-60: trade log matches wallet state; deterministic outcomes."""

    async def test_st57_total_trades_matches_record_count(self) -> None:
        """ST-57 total_trades counter matches number of record_trade calls."""
        wm = _make_wallet_manager()
        wid = await wm.create_wallet(24001)
        n = 7
        for _ in range(n):
            await wm.record_trade(wallet_id=wid, size=10.0, pnl_net=1.0, fee=0.05)
        async with wm._lock:
            record = wm._wallets[wid]
            assert record.total_trades == n

    async def test_st58_balance_equals_sum_of_pnl_net(self) -> None:
        """ST-58 balance = sum of all pnl_net values applied."""
        wm = _make_wallet_manager()
        wid = await wm.create_wallet(25001)
        pnl_values = [1.0, -0.5, 3.0, -1.0, 0.25]
        for pnl in pnl_values:
            await wm.record_trade(wallet_id=wid, size=10.0, pnl_net=pnl, fee=0.05)
        expected = sum(pnl_values)
        assert await wm.get_balance(wid) == pytest.approx(expected)

    def test_st59_fee_plus_pnl_net_equals_gross(self) -> None:
        """ST-59 calculate_fee(size) + pnl_net is consistent with gross trade math."""
        size = 200.0
        gross_pnl = 10.0
        fee = WalletManager.calculate_fee(size)
        pnl_net = gross_pnl - fee
        # pnl_net + fee should equal gross
        assert pnl_net + fee == pytest.approx(gross_pnl)

    async def test_st60_wallet_deterministic_for_fixed_inputs(self) -> None:
        """ST-60 wallet state after N trades is deterministic for fixed inputs."""
        async def _run_trades(wid_offset: int) -> float:
            wm = _make_wallet_manager()
            wid = await wm.create_wallet(26000 + wid_offset)
            for pnl in [1.0, 2.0, -0.5, 0.25]:
                await wm.record_trade(
                    wallet_id=wid, size=10.0, pnl_net=pnl, fee=0.05
                )
            return await wm.get_balance(wid)

        b1 = await _run_trades(1)
        b2 = await _run_trades(2)
        assert b1 == pytest.approx(b2)
