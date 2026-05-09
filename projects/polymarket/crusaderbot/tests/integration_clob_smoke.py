"""Integration smoke test for ClobAdapter — manual run only.

Skipped in CI by default. To run:

    POLYMARKET_API_KEY=... \\
    POLYMARKET_API_SECRET=... \\
    POLYMARKET_API_PASSPHRASE=... \\
    POLYMARKET_PRIVATE_KEY=0x... \\
    USE_REAL_CLOB=1 \\
    CLOB_SMOKE=1 \\
    pytest projects/polymarket/crusaderbot/tests/integration_clob_smoke.py -v -s

This file's name intentionally does NOT match ``test_*.py`` so the
default discovery in ``pytest.ini`` won't pick it up. Pass it as a
positional argument instead. The functions are still named
``test_*`` so pytest treats them as tests once the file is targeted.

Hard rules:
  * Read-only on the broker by default. The post/cancel exercise is
    gated behind ``CLOB_SMOKE_WRITE=1`` and posts a single dust order
    well below any sane size threshold, then immediately cancels it.
  * Never auto-runs in CI. ``CLOB_SMOKE`` env flag is required.
  * Every assertion is a soft probe — a failure here is an integration
    issue, not a unit-test regression. CI must stay green even when
    the live broker is degraded.
"""
from __future__ import annotations

import os

import pytest

from projects.polymarket.crusaderbot.config import get_settings
from projects.polymarket.crusaderbot.integrations.clob import (
    ClobAdapter,
    MarketDataClient,
    get_clob_client,
)


SMOKE_ENABLED = os.environ.get("CLOB_SMOKE") == "1"
SMOKE_WRITE = os.environ.get("CLOB_SMOKE_WRITE") == "1"

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not SMOKE_ENABLED,
        reason="CLOB_SMOKE=1 not set — integration smoke is opt-in",
    ),
]


# --- Read-only path -------------------------------------------------


async def test_market_data_orderbook_round_trip():
    """Pick a known token (USDC market id is set in env) and fetch the
    book. Validates DNS, TLS, and response shape end-to-end.
    """
    token_id = os.environ.get("CLOB_SMOKE_TOKEN_ID")
    if not token_id:
        pytest.skip("CLOB_SMOKE_TOKEN_ID not set — cannot probe a real book")
    async with MarketDataClient() as md:
        book = await md.get_orderbook(token_id)
    assert "bids" in book and "asks" in book


async def test_factory_returns_real_adapter_when_use_real_clob_set():
    settings = get_settings()
    if not settings.USE_REAL_CLOB:
        pytest.skip("USE_REAL_CLOB unset — adapter smoke skipped")
    client = get_clob_client(settings)
    assert isinstance(client, ClobAdapter)
    assert client.address.startswith("0x")
    await client.aclose()


# --- Write path (gated) --------------------------------------------


@pytest.mark.skipif(
    not SMOKE_WRITE,
    reason="CLOB_SMOKE_WRITE=1 not set — write path is opt-in",
)
async def test_post_then_cancel_dust_order():
    """Post a dust limit order well below any practical execution size,
    then immediately cancel. Operator MUST run this only on a wallet
    with negligible balance — ``warning`` line is printed before any
    POST so the operator can ctrl+C if invoked by accident.
    """
    settings = get_settings()
    token_id = os.environ.get("CLOB_SMOKE_TOKEN_ID")
    if not (settings.USE_REAL_CLOB and token_id):
        pytest.skip("USE_REAL_CLOB or CLOB_SMOKE_TOKEN_ID missing")

    print("\n[CLOB_SMOKE_WRITE] About to POST a real dust order. Ctrl+C aborts.")

    client = get_clob_client(settings)
    try:
        placed = await client.post_order(
            token_id=token_id, side="BUY", price=0.01, size=1.0,
        )
        order_id = placed.get("orderID") or placed.get("orderID")
        assert order_id, f"no orderID in response: {placed!r}"
        cancelled = await client.cancel_order(order_id)
        print(f"[CLOB_SMOKE_WRITE] cancel response: {cancelled}")
    finally:
        await client.aclose()
