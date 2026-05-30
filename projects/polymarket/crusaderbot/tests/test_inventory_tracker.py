"""Per-market inventory tracker foundation
(WARP/R00T/inventory-tracker-foundation, ref Polybot directive §5).

Foundation lane: pin the data structure + aggregation contract that
future lanes (Safe Close direction override, Flip Hunter fast top-up,
cross-strategy exposure cap) will consume. No execution-layer change
in this lane; behavioural pinning is the dataclass shape + the SQL
aggregation surface.

Module under test:
  ``projects.polymarket.crusaderbot.domain.strategy.inventory``
"""
from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from projects.polymarket.crusaderbot.domain.strategy.inventory import (
    MarketInventory,
    _LIVE_POSITION_STATUSES,
    compute_market_inventory,
)


_MARKET_ID = "inv-market-1"


def _row(side: str, total_size: float, n: int) -> dict:
    """Simulate an asyncpg row (dict-like with __getitem__)."""
    return {"side": side, "total_size": total_size, "n": n}


def _conn(rows: list[dict]):
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=rows)
    return conn


# ---------------------------------------------------------------------
# Dataclass invariants — math + property shape.
# ---------------------------------------------------------------------


def test_market_inventory_imbalance_yes_heavy():
    inv = MarketInventory(
        user_id="u-1", market_id=_MARKET_ID,
        yes_size_usdc=Decimal("80"), no_size_usdc=Decimal("20"),
        yes_count=2, no_count=1,
    )
    assert inv.imbalance_usdc == Decimal("60")
    assert inv.total_size_usdc == Decimal("100")
    assert inv.imbalance_pct == Decimal("0.6")
    assert inv.is_empty is False


def test_market_inventory_imbalance_no_heavy():
    inv = MarketInventory(
        user_id="u-1", market_id=_MARKET_ID,
        yes_size_usdc=Decimal("10"), no_size_usdc=Decimal("90"),
        yes_count=1, no_count=3,
    )
    assert inv.imbalance_usdc == Decimal("-80")
    assert inv.imbalance_pct == Decimal("-0.8")


def test_market_inventory_balanced():
    inv = MarketInventory(
        user_id="u-1", market_id=_MARKET_ID,
        yes_size_usdc=Decimal("50"), no_size_usdc=Decimal("50"),
        yes_count=1, no_count=1,
    )
    assert inv.imbalance_usdc == Decimal("0")
    assert inv.imbalance_pct == Decimal("0")
    assert inv.is_empty is False


def test_market_inventory_empty_pct_is_none():
    """Avoid divide-by-zero when both legs are empty — `None` is the
    documented sentinel for 'no position to be imbalanced against'."""
    inv = MarketInventory.empty("u-1", _MARKET_ID)
    assert inv.imbalance_pct is None
    assert inv.imbalance_usdc == Decimal("0")
    assert inv.is_empty is True


def test_market_inventory_empty_coerces_uuid():
    """`empty()` must coerce a UUID user_id to str — the dataclass
    typing says `user_id: str` so passing a UUID would otherwise
    flow through unconverted and break equality / serialisation
    downstream."""
    from uuid import UUID
    uid = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    inv = MarketInventory.empty(uid, _MARKET_ID)
    assert isinstance(inv.user_id, str)
    assert inv.user_id == str(uid)


def test_market_inventory_is_frozen():
    """Dataclass is frozen so consumers can pass it through async
    contexts / cache it without worrying about mutation. Pin the
    contract here with the specific FrozenInstanceError so a refactor
    that flips `frozen=False` (and therefore swallows the AttributeError
    that this previously caught) surfaces immediately."""
    inv = MarketInventory.empty("u-1", _MARKET_ID)
    with pytest.raises(FrozenInstanceError):
        inv.yes_size_usdc = Decimal("99")  # type: ignore[misc]


# ---------------------------------------------------------------------
# Aggregation contract — `compute_market_inventory` SQL surface.
# ---------------------------------------------------------------------


def test_compute_aggregates_yes_and_no():
    """Two rows from the SQL aggregation (one per side) populate both
    legs of the dataclass."""
    conn = _conn([_row("yes", 75.0, 2), _row("no", 25.0, 1)])
    inv = asyncio.run(compute_market_inventory(conn, uuid4(), _MARKET_ID))
    assert inv.yes_size_usdc == Decimal("75")
    assert inv.no_size_usdc == Decimal("25")
    assert inv.yes_count == 2
    assert inv.no_count == 1
    assert inv.imbalance_usdc == Decimal("50")


def test_compute_yes_only():
    """A user holding only a YES position has zero NO exposure — the
    `no_size_usdc` must default to Decimal('0'), not None."""
    conn = _conn([_row("yes", 40.0, 1)])
    inv = asyncio.run(compute_market_inventory(conn, uuid4(), _MARKET_ID))
    assert inv.yes_size_usdc == Decimal("40")
    assert inv.no_size_usdc == Decimal("0")
    assert inv.no_count == 0
    assert inv.imbalance_usdc == Decimal("40")


def test_compute_no_only():
    conn = _conn([_row("no", 30.0, 1)])
    inv = asyncio.run(compute_market_inventory(conn, uuid4(), _MARKET_ID))
    assert inv.no_size_usdc == Decimal("30")
    assert inv.yes_size_usdc == Decimal("0")
    assert inv.imbalance_usdc == Decimal("-30")


def test_compute_no_rows_returns_empty():
    """A user with no live positions on the market → empty inventory
    (zeros), not None / raise. Callers can treat empty the same as
    'no inventory data' without a branch."""
    conn = _conn([])
    inv = asyncio.run(compute_market_inventory(conn, uuid4(), _MARKET_ID))
    assert inv.is_empty is True
    assert inv.yes_size_usdc == Decimal("0")
    assert inv.no_size_usdc == Decimal("0")


def test_compute_normalises_uppercase_side_labels():
    """SQL projects ``LOWER(side)`` AND the Python loop also calls
    ``.lower()`` defensively. Feed UPPERCASE labels so the test
    actually exercises the normalisation path (catches a regression
    that removed `.lower()` from the loop — the SQL projection alone
    would still bucket correctly, but the loop's defensive layer
    matters when a mocked/test conn bypasses the SQL).
    """
    conn = _conn([_row("YES", 10.0, 1), _row("No", 20.0, 1)])
    inv = asyncio.run(compute_market_inventory(conn, uuid4(), _MARKET_ID))
    assert inv.yes_size_usdc == Decimal("10")
    assert inv.no_size_usdc == Decimal("20")


def test_compute_ignores_unknown_side_label():
    """Defensive: a corrupted row with side='foo' is dropped silently
    rather than crashing the scan tick. The known sides still
    aggregate correctly."""
    conn = _conn([_row("foo", 100.0, 5), _row("yes", 10.0, 1)])
    inv = asyncio.run(compute_market_inventory(conn, uuid4(), _MARKET_ID))
    assert inv.yes_size_usdc == Decimal("10")
    assert inv.no_size_usdc == Decimal("0")
    # Unknown rows do NOT inflate counts.
    assert inv.yes_count == 1
    assert inv.no_count == 0


def test_compute_handles_decimal_strings():
    """asyncpg returns NUMERIC columns as Decimal but tests pass
    floats / Decimal strings; the helper must accept both via
    ``Decimal(str(...))`` rather than ``Decimal(...)`` directly (the
    float path triggers a DeprecationWarning on Decimal+float)."""
    conn = _conn([_row("yes", "12.345678", 1)])
    inv = asyncio.run(compute_market_inventory(conn, uuid4(), _MARKET_ID))
    assert inv.yes_size_usdc == Decimal("12.345678")


def test_compute_decimal_fast_path():
    """Production asyncpg decodes NUMERIC directly to Decimal; the
    helper must reuse the value without a `str()` round-trip
    (preserves precision + avoids unnecessary allocation in the
    scanner hot path).
    """
    incoming = Decimal("42.123456")
    conn = _conn([_row("yes", incoming, 1)])
    inv = asyncio.run(compute_market_inventory(conn, uuid4(), _MARKET_ID))
    # Same Decimal value — and same identity proves no str-coercion
    # round-trip happened in the fast path.
    assert inv.yes_size_usdc == incoming
    assert inv.yes_size_usdc is incoming


def test_compute_handles_none_size():
    """A row whose `total_size` is NULL (impossible per the GROUP BY
    but defensive) must yield zero, not raise."""
    conn = _conn([_row("yes", None, 0)])
    inv = asyncio.run(compute_market_inventory(conn, uuid4(), _MARKET_ID))
    assert inv.yes_size_usdc == Decimal("0")


def test_compute_uses_live_status_filter():
    """The aggregation query MUST filter by ``status = ANY(...)`` with
    the live-status whitelist so closed / expired positions never
    inflate live exposure. Pin via the asyncpg call signature.
    """
    conn = _conn([])
    asyncio.run(compute_market_inventory(conn, uuid4(), _MARKET_ID))
    call_args = conn.fetch.call_args
    sql = call_args.args[0]
    assert "status = ANY" in sql, (
        "Regression: compute_market_inventory must filter by live "
        "statuses — closed/expired rows would double-count cost basis."
    )
    # The third positional arg is the live-status list passed to the
    # ANY($3::text[]) parameter; verify it's exactly the constant the
    # module exports (no silent drift to a wider set).
    assert set(call_args.args[3]) == set(_LIVE_POSITION_STATUSES)


def test_compute_passes_query_timeout():
    """CLAUDE.md `Resilience: retry + backoff + timeout on all external
    calls`. The asyncpg fetch MUST be invoked with the documented
    timeout so a stalled socket / locked row can't hang the entire
    scan tick once this gets wired in Lane D-2.
    """
    from projects.polymarket.crusaderbot.domain.strategy.inventory import (
        _INVENTORY_QUERY_TIMEOUT_SEC,
    )
    conn = _conn([])
    asyncio.run(compute_market_inventory(conn, uuid4(), _MARKET_ID))
    call_args = conn.fetch.call_args
    assert "timeout" in call_args.kwargs, (
        "Regression: compute_market_inventory dropped its query timeout. "
        "Without it a hung socket would stall the scan tick."
    )
    assert call_args.kwargs["timeout"] == _INVENTORY_QUERY_TIMEOUT_SEC


def test_live_position_statuses_pinned():
    """Pin the module-level constant so a future edit that adds 'closed'
    or removes 'pending_settlement' surfaces immediately."""
    assert _LIVE_POSITION_STATUSES == frozenset({"open", "pending_settlement"}), (
        "Regression: _LIVE_POSITION_STATUSES drift. 'closed' must NEVER "
        "be added (double-counts cost basis); 'pending_settlement' must "
        "stay so pre-resolution exposure is captured."
    )
