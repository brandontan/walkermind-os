"""Per-user deposit-wallet awareness in the deposit watcher (Step 3).

Step 2 (#1736) persisted ``wallets.polymarket_deposit_wallet`` — the
EIP-7702 deposit wallet sig-3 orders sign against. The watcher now also
scans transfers into that address so any deposit surface (EOA / Safe
proxy / Polymarket deposit wallet) credits the right user.

These tests pin the watcher contract: three addresses per wallet, NULL
columns fall back, duplicates are collapsed, and the SELECT pulls the
right column.
"""
from __future__ import annotations

import uuid as _uuid

from projects.polymarket.crusaderbot.scheduler import _build_watched_addresses


_EOA = "0xAAaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaAA01"
_SAFE = "0xBBbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbBB01"
_DW = "0xCCccccccccccccccccccccccccccccccccccCC01"


def test_polymarket_deposit_wallet_is_watched_when_set() -> None:
    """A wallet with a non-null polymarket_deposit_wallet contributes all
    three surfaces, all routing to the same user."""
    uid = _uuid.uuid4()
    rows = [{
        "user_id": uid,
        "deposit_address": _EOA,
        "safe_address": _SAFE,
        "polymarket_deposit_wallet": _DW,
    }]
    addresses, lookup = _build_watched_addresses(rows)
    lower = {a.lower() for a in addresses}
    assert lower == {_EOA.lower(), _SAFE.lower(), _DW.lower()}
    # Every address resolves to the same user — partial-unique indexes on
    # all three columns (migrations 061/094) guarantee no cross-user
    # collision at the DB layer; the watcher's lookup map mirrors that.
    assert lookup[_EOA.lower()] == uid
    assert lookup[_SAFE.lower()] == uid
    assert lookup[_DW.lower()] == uid


def test_polymarket_deposit_wallet_null_falls_back() -> None:
    """Pre-Step-2 wallets (column NULL) keep working — EOA + Safe only."""
    uid = _uuid.uuid4()
    rows = [{
        "user_id": uid,
        "deposit_address": _EOA,
        "safe_address": _SAFE,
        "polymarket_deposit_wallet": None,
    }]
    addresses, lookup = _build_watched_addresses(rows)
    assert len(addresses) == 2
    assert _DW.lower() not in lookup


def test_all_three_columns_null_except_eoa_falls_back() -> None:
    """A brand-new wallet (Safe SDK unavailable + deposit wallet not yet
    backfilled) still routes EOA deposits — neither backfill blocks the
    watcher from working at all."""
    uid = _uuid.uuid4()
    rows = [{
        "user_id": uid,
        "deposit_address": _EOA,
        "safe_address": None,
        "polymarket_deposit_wallet": None,
    }]
    addresses, lookup = _build_watched_addresses(rows)
    assert addresses == [_EOA]
    assert lookup == {_EOA.lower(): uid}


def test_pre_step3_rows_without_the_column_still_work() -> None:
    """Defensive: a wallet row lacking ``polymarket_deposit_wallet`` at all
    (e.g. tests built before this lane, asyncpg Records pre-migration)
    must NOT raise. The dict .get fallback returns None, the row is
    treated like the legacy two-column path."""
    uid = _uuid.uuid4()
    rows = [{
        "user_id": uid,
        "deposit_address": _EOA,
        "safe_address": _SAFE,
        # polymarket_deposit_wallet key absent entirely
    }]
    addresses, lookup = _build_watched_addresses(rows)
    assert len(addresses) == 2
    assert _DW.lower() not in lookup


def test_duplicate_columns_are_collapsed() -> None:
    """If two columns hold the SAME address (rare: SDK returns the EOA as
    the deposit wallet) the watcher records it ONCE — no duplicate
    eth_getLogs scan, no map collision."""
    uid = _uuid.uuid4()
    rows = [{
        "user_id": uid,
        "deposit_address": _EOA,
        "safe_address": None,
        # Polymarket SDK happens to return the EOA as the deposit wallet —
        # the dedup guard prevents a duplicate scan target.
        "polymarket_deposit_wallet": _EOA.upper(),
    }]
    addresses, lookup = _build_watched_addresses(rows)
    assert len(addresses) == 1
    assert _EOA.lower() in lookup


def test_two_users_three_addresses_each_route_correctly() -> None:
    """Multiple wallets — every surface routes to its own user, no
    cross-user lookup leakage."""
    u1, u2 = _uuid.uuid4(), _uuid.uuid4()
    eoa1, safe1, dw1 = "0x" + "1" * 40, "0x" + "2" * 40, "0x" + "3" * 40
    eoa2, safe2, dw2 = "0x" + "4" * 40, "0x" + "5" * 40, "0x" + "6" * 40
    rows = [
        {"user_id": u1, "deposit_address": eoa1, "safe_address": safe1,
         "polymarket_deposit_wallet": dw1},
        {"user_id": u2, "deposit_address": eoa2, "safe_address": safe2,
         "polymarket_deposit_wallet": dw2},
    ]
    addresses, lookup = _build_watched_addresses(rows)
    assert len(addresses) == 6
    for addr in (eoa1, safe1, dw1):
        assert lookup[addr.lower()] == u1
    for addr in (eoa2, safe2, dw2):
        assert lookup[addr.lower()] == u2


def test_watch_deposits_query_includes_deposit_wallet_column() -> None:
    """Pins the SQL: ``watch_deposits`` must SELECT polymarket_deposit_wallet
    or the column never reaches ``_build_watched_addresses`` and Step 3 is
    silently dormant on prod. A grep guard is the cheapest pin for this."""
    from pathlib import Path
    src = Path(__file__).resolve().parent.parent / "scheduler.py"
    text = src.read_text()
    assert "polymarket_deposit_wallet FROM wallets" in text, (
        "scheduler.watch_deposits must SELECT polymarket_deposit_wallet "
        "alongside deposit_address + safe_address"
    )
