"""Polygon chain reader: USDC transfer detection + balance reads.

Uses web3 v7 AsyncWeb3 with eth_getLogs (stateless) for event scanning.
Every RPC call is retry-wrapped with exponential backoff; final failures are
logged at ERROR (never silently swallowed).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from eth_utils import event_abi_to_log_topic
from tenacity import (
    AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential,
)
from web3 import AsyncHTTPProvider, AsyncWeb3
from web3.exceptions import Web3RPCError

from ..config import get_settings

logger = logging.getLogger(__name__)

ERC20_ABI: list[dict[str, Any]] = [
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "from", "type": "address"},
            {"indexed": True, "name": "to", "type": "address"},
            {"indexed": False, "name": "value", "type": "uint256"},
        ],
        "name": "Transfer",
        "type": "event",
    },
    {
        "constant": True,
        "inputs": [{"name": "owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function",
    },
]

TRANSFER_EVENT_ABI = ERC20_ABI[0]
TRANSFER_TOPIC = "0x" + event_abi_to_log_topic(TRANSFER_EVENT_ABI).hex()

_w3: Optional[AsyncWeb3] = None
_usdc = None


def _retry():
    """Retry network/RPC errors only — programmer errors aren't retried."""
    return AsyncRetrying(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((Web3RPCError, ConnectionError, TimeoutError)),
    )


def _get_w3() -> AsyncWeb3:
    global _w3, _usdc
    if _w3 is None:
        settings = get_settings()
        _w3 = AsyncWeb3(AsyncHTTPProvider(settings.POLYGON_RPC_URL))
        try:
            from web3.middleware import ExtraDataToPOAMiddleware
            _w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        except Exception as exc:
            logger.warning("ExtraDataToPOA inject skipped: %s", exc)
        _usdc = _w3.eth.contract(
            address=AsyncWeb3.to_checksum_address(settings.USDC_POLYGON),
            abi=ERC20_ABI,
        )
    return _w3


def _usdc_contract():
    _get_w3()
    return _usdc


async def get_native_balance(address: str) -> float:
    w3 = _get_w3()
    checksum = AsyncWeb3.to_checksum_address(address)
    try:
        async for attempt in _retry():
            with attempt:
                wei = await w3.eth.get_balance(checksum)
        return float(w3.from_wei(wei, "ether"))
    except Exception as exc:
        logger.error("get_native_balance permanently failed for %s: %s",
                     address, exc)
        return 0.0


async def get_usdc_balance(address: str) -> float:
    contract = _usdc_contract()
    settings = get_settings()
    checksum = AsyncWeb3.to_checksum_address(address)
    try:
        async for attempt in _retry():
            with attempt:
                raw = await contract.functions.balanceOf(checksum).call()
        return raw / (10 ** settings.USDC_DECIMALS)
    except Exception as exc:
        logger.error("get_usdc_balance permanently failed for %s: %s",
                     address, exc)
        return 0.0


async def latest_block() -> int:
    w3 = _get_w3()
    async for attempt in _retry():
        with attempt:
            return int(await w3.eth.block_number)
    return 0  # unreachable; tenacity reraises


async def gas_price_gwei() -> float:
    """Current Polygon base gas price in gwei. Retried; raises on permanent failure
    so callers (e.g. instant-redeem gas guard) can fall back safely.
    """
    w3 = _get_w3()
    async for attempt in _retry():
        with attempt:
            wei = await w3.eth.gas_price
    return float(wei) / 1e9


def _addr_to_topic(address: str) -> str:
    """Pad 20-byte address into a 32-byte topic (left-padded with zeros)."""
    addr = AsyncWeb3.to_checksum_address(address).lower()[2:]
    return "0x" + ("0" * 24) + addr


async def scan_usdc_transfers(
    addresses: list[str], from_block: int, to_block: int,
) -> list[dict[str, Any]]:
    """Return all USDC Transfer events into any of the given addresses.

    Raises on permanent RPC failure (after retries) so the caller can refuse
    to advance its block cursor.
    """
    if not addresses or from_block > to_block:
        return []
    w3 = _get_w3()
    settings = get_settings()
    contract = _usdc_contract()
    to_topics = [_addr_to_topic(a) for a in addresses]
    async for attempt in _retry():
        with attempt:
            logs = await w3.eth.get_logs({
                "fromBlock": from_block,
                "toBlock": to_block,
                "address": AsyncWeb3.to_checksum_address(settings.USDC_POLYGON),
                "topics": [TRANSFER_TOPIC, None, to_topics],
            })
    out = []
    for log in logs:
        try:
            decoded = contract.events.Transfer().process_log(log)
            out.append({
                "tx_hash": log["transactionHash"].hex(),
                "block_number": int(log["blockNumber"]),
                "from": decoded["args"]["from"],
                "to": decoded["args"]["to"],
                "amount": decoded["args"]["value"] / (10 ** settings.USDC_DECIMALS),
            })
        except Exception as exc:
            logger.error("decode log failed (skipping entry): %s", exc)
            continue
    return out


async def scan_from_cursor(
    addresses: list[str], cursor: int, lookback: int = 2000, max_range: int = 1000,
) -> tuple[list[dict[str, Any]], int]:
    """Scan from `cursor` (or head-lookback if cursor==0) up to head.

    Returns (transfers, scanned_to_block). The caller is responsible for
    persisting `scanned_to_block` only after every transfer has been
    successfully processed. Raises on permanent RPC failure.
    """
    head = await latest_block()
    start = cursor + 1 if cursor > 0 else max(head - lookback, 0)
    if start > head:
        return [], cursor
    end = min(head, start + max_range - 1)
    transfers = await scan_usdc_transfers(addresses, start, end)
    return transfers, end
