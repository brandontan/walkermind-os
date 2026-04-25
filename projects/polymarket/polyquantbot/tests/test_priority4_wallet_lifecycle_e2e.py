"""Priority 4 — Wallet Lifecycle Foundation: end-to-end tests.

Covers sections 25–30 of WORKTODO.md:
  WL-01..WL-05  Section 25 — domain model + transition guards
  WL-06..WL-11  Section 26 — lifecycle FSM (create/link/activate/deactivate)
  WL-12..WL-14  Section 27 — persistence (upsert + load + audit trail)
  WL-15..WL-18  Section 28 — auth boundary (ownership + privilege guard)
  WL-19..WL-21  Section 29 — wallet status display (surface)
  WL-22..WL-25  Section 30 — recovery (broken-link, duplicate, stale)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from projects.polymarket.polyquantbot.server.schemas.wallet_lifecycle import (
    WalletAuditEntry,
    WalletLifecycleRecord,
    WalletLifecycleStatus,
    WalletLifecycleTransitionResult,
    is_valid_transition,
    new_log_id,
    new_wallet_id,
    requires_admin,
    utc_now,
)
from projects.polymarket.polyquantbot.server.services.wallet_lifecycle_service import (
    WalletLifecycleService,
)
from projects.polymarket.polyquantbot.platform.wallet_auth.wallet_lifecycle_foundation import (
    WalletOwnershipBoundary,
    WalletOwnershipPolicy,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_store(*, get_wallet=None, get_by_address=None, list_wallets=None, list_audit=None):
    store = AsyncMock()
    store.get_wallet.return_value = get_wallet
    store.get_wallet_by_address.return_value = get_by_address
    store.list_wallets_for_user.return_value = list_wallets or []
    store.list_audit_for_wallet.return_value = list_audit or []
    store.upsert_wallet.return_value = True
    store.append_audit.return_value = True
    store.transition_atomic.return_value = "ok"
    return store


def _make_wallet(
    *,
    wallet_id: str = "wlc_test000001",
    tenant_id: str = "t1",
    user_id: str = "u1",
    address: str = "0xABCD" * 10,
    status: WalletLifecycleStatus = WalletLifecycleStatus.UNLINKED,
    previous_status: WalletLifecycleStatus | None = None,
    changed_by: str = "u1",
) -> WalletLifecycleRecord:
    now = utc_now()
    return WalletLifecycleRecord(
        wallet_id=wallet_id,
        tenant_id=tenant_id,
        user_id=user_id,
        address=address,
        status=status,
        previous_status=previous_status,
        status_changed_at=now,
        changed_by=changed_by,
        created_at=now,
    )


# ── Section 25: Domain model + transition guards ──────────────────────────────

def test_wl01_status_enum_values():
    """WL-01: All five lifecycle states exist."""
    assert WalletLifecycleStatus.UNLINKED.value == "unlinked"
    assert WalletLifecycleStatus.LINKED.value == "linked"
    assert WalletLifecycleStatus.ACTIVE.value == "active"
    assert WalletLifecycleStatus.DEACTIVATED.value == "deactivated"
    assert WalletLifecycleStatus.BLOCKED.value == "blocked"


def test_wl02_valid_transitions():
    """WL-02: Forward transitions are allowed."""
    S = WalletLifecycleStatus
    assert is_valid_transition(S.UNLINKED, S.LINKED)
    assert is_valid_transition(S.LINKED, S.ACTIVE)
    assert is_valid_transition(S.ACTIVE, S.DEACTIVATED)
    assert is_valid_transition(S.LINKED, S.DEACTIVATED)
    assert is_valid_transition(S.DEACTIVATED, S.LINKED)


def test_wl03_invalid_transitions():
    """WL-03: Invalid transitions are rejected."""
    S = WalletLifecycleStatus
    assert not is_valid_transition(S.UNLINKED, S.ACTIVE)
    assert not is_valid_transition(S.ACTIVE, S.UNLINKED)
    assert not is_valid_transition(S.BLOCKED, S.ACTIVE)
    assert not is_valid_transition(S.DEACTIVATED, S.ACTIVE)
    assert not is_valid_transition(S.UNLINKED, S.BLOCKED)


def test_wl04_admin_only_transitions():
    """WL-04: Block and unblock require admin."""
    S = WalletLifecycleStatus
    assert requires_admin(S.ACTIVE, S.BLOCKED)
    assert requires_admin(S.LINKED, S.BLOCKED)
    assert requires_admin(S.BLOCKED, S.LINKED)


def test_wl05_non_admin_transitions_do_not_require_admin():
    """WL-05: Normal user transitions do not require admin."""
    S = WalletLifecycleStatus
    assert not requires_admin(S.UNLINKED, S.LINKED)
    assert not requires_admin(S.LINKED, S.ACTIVE)
    assert not requires_admin(S.ACTIVE, S.DEACTIVATED)
    assert not requires_admin(S.DEACTIVATED, S.LINKED)


# ── Section 26: Wallet lifecycle FSM ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_wl06_create_wallet_ok():
    """WL-06: Create wallet succeeds when address is new."""
    store = _make_store(get_by_address=None)
    svc = WalletLifecycleService(store=store)
    result = await svc.create_wallet(
        tenant_id="t1", user_id="u1", address="0xNEW",
        changed_by="u1",
    )
    assert result.outcome == "ok"
    assert result.wallet is not None
    assert result.wallet.status == WalletLifecycleStatus.UNLINKED
    assert result.audit_entry is not None
    assert result.audit_entry.from_status is None
    assert result.audit_entry.to_status == WalletLifecycleStatus.UNLINKED


@pytest.mark.asyncio
async def test_wl07_create_wallet_duplicate_address():
    """WL-07: Create wallet fails when address already registered."""
    existing = _make_wallet(status=WalletLifecycleStatus.LINKED)
    store = _make_store(get_by_address=existing)
    svc = WalletLifecycleService(store=store)
    result = await svc.create_wallet(
        tenant_id="t1", user_id="u1", address="0xDUP", changed_by="u1",
    )
    assert result.outcome == "duplicate_address"
    assert result.wallet is existing


@pytest.mark.asyncio
async def test_wl08_link_wallet_ok():
    """WL-08: Link wallet transitions unlinked → linked."""
    w = _make_wallet(status=WalletLifecycleStatus.UNLINKED)
    store = _make_store(get_wallet=w)
    svc = WalletLifecycleService(store=store)
    result = await svc.link_wallet(
        wallet_id=w.wallet_id, user_id="u1", tenant_id="t1", changed_by="u1",
    )
    assert result.outcome == "ok"
    assert result.wallet.status == WalletLifecycleStatus.LINKED
    assert result.wallet.previous_status == WalletLifecycleStatus.UNLINKED


@pytest.mark.asyncio
async def test_wl09_activate_wallet_ok():
    """WL-09: Activate wallet transitions linked → active."""
    w = _make_wallet(status=WalletLifecycleStatus.LINKED)
    store = _make_store(get_wallet=w)
    svc = WalletLifecycleService(store=store)
    result = await svc.activate_wallet(
        wallet_id=w.wallet_id, user_id="u1", tenant_id="t1", changed_by="u1",
    )
    assert result.outcome == "ok"
    assert result.wallet.status == WalletLifecycleStatus.ACTIVE


@pytest.mark.asyncio
async def test_wl10_deactivate_wallet_ok():
    """WL-10: Deactivate wallet transitions active → deactivated."""
    w = _make_wallet(status=WalletLifecycleStatus.ACTIVE)
    store = _make_store(get_wallet=w)
    svc = WalletLifecycleService(store=store)
    result = await svc.deactivate_wallet(
        wallet_id=w.wallet_id, user_id="u1", tenant_id="t1", changed_by="u1",
    )
    assert result.outcome == "ok"
    assert result.wallet.status == WalletLifecycleStatus.DEACTIVATED


@pytest.mark.asyncio
async def test_wl11_invalid_transition_rejected():
    """WL-11: Invalid transition (unlinked → active) is rejected."""
    w = _make_wallet(status=WalletLifecycleStatus.UNLINKED)
    store = _make_store(get_wallet=w)
    svc = WalletLifecycleService(store=store)
    result = await svc.activate_wallet(
        wallet_id=w.wallet_id, user_id="u1", tenant_id="t1", changed_by="u1",
    )
    assert result.outcome == "invalid_transition"
    assert result.wallet is w


# ── Section 27: Secure wallet persistence ────────────────────────────────────

@pytest.mark.asyncio
async def test_wl12_upsert_called_on_transition():
    """WL-12: Atomic transition is called on each state change."""
    w = _make_wallet(status=WalletLifecycleStatus.UNLINKED)
    store = _make_store(get_wallet=w)
    svc = WalletLifecycleService(store=store)
    await svc.link_wallet(wallet_id=w.wallet_id, user_id="u1", tenant_id="t1", changed_by="u1")
    store.transition_atomic.assert_awaited_once()


@pytest.mark.asyncio
async def test_wl13_audit_appended_on_transition():
    """WL-13: Audit trail entry is appended on each successful transition."""
    w = _make_wallet(status=WalletLifecycleStatus.LINKED)
    store = _make_store(get_wallet=w)
    svc = WalletLifecycleService(store=store)
    result = await svc.activate_wallet(
        wallet_id=w.wallet_id, user_id="u1", tenant_id="t1", changed_by="u1",
    )
    assert result.audit_entry is not None
    assert result.audit_entry.from_status == WalletLifecycleStatus.LINKED
    assert result.audit_entry.to_status == WalletLifecycleStatus.ACTIVE
    store.transition_atomic.assert_awaited_once()


@pytest.mark.asyncio
async def test_wl14_audit_trail_retrieved():
    """WL-14: Audit trail can be retrieved for a wallet."""
    now = utc_now()
    audit = WalletAuditEntry(
        log_id="wal_abc",
        wallet_id="wlc_001",
        from_status=None,
        to_status=WalletLifecycleStatus.UNLINKED,
        changed_at=now,
        changed_by="u1",
        reason="wallet_created",
    )
    store = _make_store(list_audit=[audit])
    svc = WalletLifecycleService(store=store)
    trail = await svc.get_audit_trail("wlc_001")
    assert len(trail) == 1
    assert trail[0].reason == "wallet_created"


# ── Section 28: Auth boundary ─────────────────────────────────────────────────

def test_wl15_ownership_ok():
    """WL-15: Ownership check passes when user owns wallet."""
    boundary = WalletOwnershipBoundary()
    w = _make_wallet(tenant_id="t1", user_id="u1", status=WalletLifecycleStatus.LINKED)
    policy = WalletOwnershipPolicy(wallet_id=w.wallet_id, tenant_id="t1", requesting_user_id="u1")
    result = boundary.verify_ownership(policy, w)
    assert result.outcome == "ok"


def test_wl16_ownership_denied_wrong_user():
    """WL-16: Ownership check fails when different user requests."""
    boundary = WalletOwnershipBoundary()
    w = _make_wallet(tenant_id="t1", user_id="u1", status=WalletLifecycleStatus.LINKED)
    policy = WalletOwnershipPolicy(wallet_id=w.wallet_id, tenant_id="t1", requesting_user_id="u2")
    result = boundary.verify_ownership(policy, w)
    assert result.outcome == "ownership_denied"


def test_wl17_blocked_wallet_hidden_from_non_admin():
    """WL-17: BLOCKED wallet returns wallet_blocked for non-admin."""
    boundary = WalletOwnershipBoundary()
    w = _make_wallet(user_id="u1", status=WalletLifecycleStatus.BLOCKED)
    policy = WalletOwnershipPolicy(wallet_id=w.wallet_id, tenant_id="t1", requesting_user_id="u1")
    result = boundary.verify_ownership(policy, w)
    assert result.outcome == "wallet_blocked"


def test_wl18_admin_can_see_blocked_wallet():
    """WL-18: Admin can access BLOCKED wallet."""
    boundary = WalletOwnershipBoundary()
    w = _make_wallet(user_id="u1", status=WalletLifecycleStatus.BLOCKED)
    policy = WalletOwnershipPolicy(
        wallet_id=w.wallet_id, tenant_id="t1", requesting_user_id="admin1", is_admin=True,
    )
    result = boundary.verify_ownership(policy, w)
    assert result.outcome == "ok"


# ── Section 29: Wallet status surface ────────────────────────────────────────

@pytest.mark.asyncio
async def test_wl19_lifecycle_status_display_no_wallets():
    """WL-19: Status display returns helpful message when no wallets."""
    from projects.polymarket.polyquantbot.telegram.handlers import wallet as wh
    svc = AsyncMock()
    svc.list_wallets.return_value = []
    wh._wallet_lifecycle_service = svc
    text, _ = await wh.handle_wallet_lifecycle_status("t1", "u1")
    assert "No wallets" in text
    wh._wallet_lifecycle_service = None


@pytest.mark.asyncio
async def test_wl20_lifecycle_status_display_with_wallet():
    """WL-20: Status display renders wallet status safely (address masked)."""
    from projects.polymarket.polyquantbot.telegram.handlers import wallet as wh
    w = _make_wallet(address="0x1234567890abcdef", status=WalletLifecycleStatus.ACTIVE)
    svc = AsyncMock()
    svc.list_wallets.return_value = [w]
    wh._wallet_lifecycle_service = svc
    text, _ = await wh.handle_wallet_lifecycle_status("t1", "u1")
    assert "active" in text
    assert "0x1234" in text
    assert "0x1234567890abcdef" not in text  # full address must NOT appear
    wh._wallet_lifecycle_service = None


@pytest.mark.asyncio
async def test_wl21_lifecycle_status_display_no_service():
    """WL-21: Status display handles missing service gracefully."""
    from projects.polymarket.polyquantbot.telegram.handlers import wallet as wh
    wh._wallet_lifecycle_service = None
    text, _ = await wh.handle_wallet_lifecycle_status("t1", "u1")
    assert "not available" in text.lower()


# ── Section 30: Recovery ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_wl22_recover_deactivated_wallet():
    """WL-22: Recovery re-links a deactivated wallet."""
    w = _make_wallet(status=WalletLifecycleStatus.DEACTIVATED)
    store = _make_store(get_wallet=w)
    svc = WalletLifecycleService(store=store)
    result = await svc.recover_wallet(
        wallet_id=w.wallet_id, user_id="u1", tenant_id="t1", changed_by="u1",
    )
    assert result.outcome == "ok"
    assert result.wallet.status == WalletLifecycleStatus.LINKED


@pytest.mark.asyncio
async def test_wl23_recover_stale_returns_stale_recovery():
    """WL-23: Recover on non-deactivated wallet returns stale_recovery."""
    w = _make_wallet(status=WalletLifecycleStatus.ACTIVE)
    store = _make_store(get_wallet=w)
    svc = WalletLifecycleService(store=store)
    result = await svc.recover_wallet(
        wallet_id=w.wallet_id, user_id="u1", tenant_id="t1", changed_by="u1",
    )
    assert result.outcome == "stale_recovery"


@pytest.mark.asyncio
async def test_wl24_block_wallet_admin_ok():
    """WL-24: Admin can block an active wallet."""
    w = _make_wallet(status=WalletLifecycleStatus.ACTIVE)
    store = _make_store(get_wallet=w)
    svc = WalletLifecycleService(store=store)
    result = await svc.block_wallet(
        wallet_id=w.wallet_id, admin_user_id="admin1", tenant_id="t1",
    )
    assert result.outcome == "ok"
    assert result.wallet.status == WalletLifecycleStatus.BLOCKED
    assert result.wallet.changed_by == "admin:admin1"


@pytest.mark.asyncio
async def test_wl25_non_admin_cannot_block():
    """WL-25: Non-admin cannot block an active wallet (privilege_error)."""
    w = _make_wallet(status=WalletLifecycleStatus.ACTIVE)
    store = _make_store(get_wallet=w)
    svc = WalletLifecycleService(store=store)
    # Call _transition directly simulating non-admin block attempt
    result = await svc._transition(
        wallet_id=w.wallet_id,
        requesting_user_id="u1",
        tenant_id="t1",
        to_status=WalletLifecycleStatus.BLOCKED,
        changed_by="u1",
        reason="test",
        is_admin=False,
    )
    assert result.outcome == "privilege_error"
