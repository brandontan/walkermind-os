"""Regression: scan_usdc_transfers decodes a NATIVE-USDC Transfer log (WARP-94).

The wrong-token alert pass scans the native-USDC contract (0x3c499c…) via the
same scan_usdc_transfers used for USDC.e. A PR review raised the concern that
decoding a log whose contract address differs from the cached USDC.e contract
would raise MismatchedABI and silently drop every native transfer. This test
exercises the REAL decode path (the end-to-end deposit sim mocks scan_from_cursor
past it) against a native-address log and asserts it decodes correctly — locking
in the address-bound decoder fix.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from web3 import AsyncHTTPProvider, AsyncWeb3

from projects.polymarket.crusaderbot.integrations import polygon

USDCE = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
NATIVE = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
TO = "0x5827edEf918dc6bf38D5b7D7bbf0A53dF5e8F808"
FROM = "0x1111111111111111111111111111111111111111"


class _Settings:
    USDC_POLYGON = USDCE
    USDC_DECIMALS = 6


def _native_log() -> dict:
    """A Transfer($2 native USDC → TO) log carrying the NATIVE contract address."""
    topic = bytes.fromhex(polygon.TRANSFER_TOPIC[2:])

    def addr_topic(a: str) -> bytes:
        return bytes.fromhex(("0" * 24) + a.lower()[2:])

    return {
        "address": AsyncWeb3.to_checksum_address(NATIVE),
        "topics": [topic, addr_topic(FROM), addr_topic(TO)],
        "data": (2_000_000).to_bytes(32, "big"),
        "blockNumber": 100,
        "transactionHash": b"\xab" * 32,
        "logIndex": 0,
        "removed": False,
        "blockHash": b"\xbb" * 32,
        "transactionIndex": 0,
    }


def test_scan_decodes_native_usdc_log():
    w3 = AsyncWeb3(AsyncHTTPProvider("http://localhost:1"))
    w3.eth.get_logs = AsyncMock(return_value=[_native_log()])

    with patch.object(polygon, "_get_w3", return_value=w3), \
         patch.object(polygon, "get_settings", return_value=_Settings()):
        out = asyncio.run(
            polygon.scan_usdc_transfers([TO], 100, 100, token_address=NATIVE)
        )

    assert len(out) == 1
    t = out[0]
    assert t["to"] == AsyncWeb3.to_checksum_address(TO)
    assert t["amount"] == 2.0  # 2_000_000 / 10**6
    assert t["removed"] is False
