"""Polygon chain reader: USDC transfer detection + balance reads.

Uses web3 v7 AsyncWeb3 with eth_getLogs (stateless) for event scanning.
Every RPC call is retry-wrapped with exponential backoff; final failures are
logged at ERROR (never silently swallowed).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from aiohttp import ClientError, ClientTimeout
from eth_utils import event_abi_to_log_topic
from tenacity import (
    AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential,
)
from web3 import AsyncHTTPProvider, AsyncWeb3
from web3.exceptions import Web3RPCError

from ..config import get_settings

logger = logging.getLogger(__name__)

# Serialize on-chain sends per from-address so concurrent capital ops (withdraw
# / sweep / redeem) never read the same nonce and collide on-chain. Process-
# local — the WebTrader + bot run as a single Fly primary, so one lock table is
# sufficient; pair this with the "pending" block tag on get_transaction_count.
_nonce_locks: dict[str, asyncio.Lock] = {}


def nonce_lock(address: str) -> asyncio.Lock:
    """Return the shared asyncio.Lock for ``address`` (case-insensitive)."""
    key = address.lower()
    lock = _nonce_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _nonce_locks[key] = lock
    return lock


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
    """Retry network/RPC errors only — programmer errors aren't retried.

    ``ClientError`` matters: web3's AsyncHTTPProvider surfaces non-2xx HTTP
    responses (Alchemy 429 throttles, 5xx blips) as aiohttp
    ``ClientResponseError`` — NOT as ``Web3RPCError`` / ``ConnectionError`` —
    so without it a single throttled response failed the whole call instead
    of backing off. ``TimeoutError`` covers ``asyncio.timeout`` deadlines
    (Python 3.11+: ``asyncio.TimeoutError is TimeoutError``).
    """
    return AsyncRetrying(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(
            (Web3RPCError, ClientError, ConnectionError, TimeoutError)
        ),
    )


# Fallback when a (test-stub) Settings object predates the field.
_DEFAULT_RPC_TIMEOUT = 20


def _rpc_deadline() -> int:
    """Per-call wall-clock ceiling for one JSON-RPC round trip."""
    return int(getattr(
        get_settings(), "POLYGON_RPC_TIMEOUT_SECONDS", _DEFAULT_RPC_TIMEOUT,
    ))


def _get_w3() -> AsyncWeb3:
    global _w3, _usdc
    if _w3 is None:
        settings = get_settings()
        # Explicit aiohttp ClientTimeout: without it the session defaults to
        # total=300s, and a peer that accepts the TCP connection but never
        # answers wedges the call for 5 minutes per retry attempt. The
        # asyncio.timeout() wrappers below are the belt to this suspender —
        # they bound the call even if a future web3/aiohttp version stops
        # honouring request_kwargs.
        _w3 = AsyncWeb3(AsyncHTTPProvider(
            settings.POLYGON_RPC_URL,
            request_kwargs={
                "timeout": ClientTimeout(total=getattr(
                    settings, "POLYGON_RPC_TIMEOUT_SECONDS",
                    _DEFAULT_RPC_TIMEOUT,
                )),
            },
        ))
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
                async with asyncio.timeout(_rpc_deadline()):
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
                async with asyncio.timeout(_rpc_deadline()):
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
            async with asyncio.timeout(_rpc_deadline()):
                return int(await w3.eth.block_number)
    return 0  # unreachable; tenacity reraises


async def gas_price_gwei() -> float:
    """Current Polygon base gas price in gwei. Retried; raises on permanent failure
    so callers (e.g. instant-redeem gas guard) can fall back safely.
    """
    w3 = _get_w3()
    async for attempt in _retry():
        with attempt:
            async with asyncio.timeout(_rpc_deadline()):
                wei = await w3.eth.gas_price
    return float(wei) / 1e9


def _addr_to_topic(address: str) -> str:
    """Pad 20-byte address into a 32-byte topic (left-padded with zeros)."""
    addr = AsyncWeb3.to_checksum_address(address).lower()[2:]
    return "0x" + ("0" * 24) + addr


async def scan_usdc_transfers(
    addresses: list[str], from_block: int, to_block: int,
    token_address: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Return all Transfer events into any of the given addresses for an ERC-20.

    ``token_address`` defaults to the USDC.e collateral contract
    (``settings.USDC_POLYGON``) — the existing deposit-credit path. Passing a
    different ERC-20 (e.g. native USDC) scans that contract instead; the
    Transfer event ABI is identical across ERC-20s so the same decoder applies.

    Raises on permanent RPC failure (after retries) so the caller can refuse
    to advance its block cursor.
    """
    if not addresses or from_block > to_block:
        return []
    w3 = _get_w3()
    settings = get_settings()
    scan_addr = token_address or settings.USDC_POLYGON
    scan_cs = AsyncWeb3.to_checksum_address(scan_addr)
    # Decode with a contract bound to the SCANNED token address rather than the
    # cached USDC.e instance. The Transfer ABI is identical across ERC-20s, so
    # decoding succeeds either way, but binding the decoder to the actual
    # address keeps it unambiguously correct for any token (e.g. native USDC).
    contract = w3.eth.contract(address=scan_cs, abi=ERC20_ABI)
    to_topics = [_addr_to_topic(a) for a in addresses]
    async for attempt in _retry():
        with attempt:
            async with asyncio.timeout(_rpc_deadline()):
                logs = await w3.eth.get_logs({
                    "fromBlock": from_block,
                    "toBlock": to_block,
                    "address": scan_cs,
                    "topics": [TRANSFER_TOPIC, None, to_topics],
                })
    out = []
    for log in logs:
        try:
            decoded = contract.events.Transfer().process_log(log)
            out.append({
                "tx_hash": log["transactionHash"].hex(),
                "log_index": int(log["logIndex"]),
                "block_number": int(log["blockNumber"]),
                "from": decoded["args"]["from"],
                "to": decoded["args"]["to"],
                "amount": decoded["args"]["value"] / (10 ** settings.USDC_DECIMALS),
                # `removed` is True when this log came from a block that was
                # orphaned by a reorg. eth_getLogs over a finalized range
                # returns False; reorg-aware subscriptions set it True so the
                # deposit watcher can un-credit a reverted transfer.
                "removed": bool(log.get("removed", False)),
            })
        except Exception as exc:
            logger.error("decode log failed (skipping entry): %s", exc)
            continue
    return out


# Smallest eth_getLogs span the adaptive scan will fall back to. If a provider
# rejects even a 31-block range the problem is not the range — reraise and let
# the caller's no-cursor-advance contract retry next tick.
_MIN_SCAN_RANGE = 31


async def scan_from_cursor(
    addresses: list[str], cursor: int, lookback: int = 2000, max_range: int = 1000,
    token_address: Optional[str] = None,
) -> tuple[list[dict[str, Any]], int]:
    """Scan from `cursor` (or head-lookback if cursor==0) up to head.

    ``token_address`` is forwarded to ``scan_usdc_transfers`` (defaults to the
    USDC.e collateral contract). Returns (transfers, scanned_to_block). The
    caller is responsible for persisting `scanned_to_block` only after every
    transfer has been successfully processed. Raises on permanent RPC failure.

    ADAPTIVE RANGE: providers cap eth_getLogs differently (block-range and
    response-size ceilings vary by vendor and plan, and the rejection arrives
    as a ``Web3RPCError`` only AFTER the in-call retries are exhausted). A
    fixed span turns such a cap into a permanent every-tick failure — the
    block-0 cursor outage mode. On a ``Web3RPCError`` the span halves down to
    ``_MIN_SCAN_RANGE``; a smaller successful scan still advances the cursor,
    so the watcher self-heals instead of wedging. Transport-level errors
    (timeouts, throttles, connection drops) are NOT halved — shrinking the
    range cannot fix those, and the per-tick retry already covers them.
    """
    head = await latest_block()
    start = cursor + 1 if cursor > 0 else max(head - lookback, 0)
    if start > head:
        return [], cursor
    span = max(int(max_range), 1)
    while True:
        end = min(head, start + span - 1)
        try:
            transfers = await scan_usdc_transfers(
                addresses, start, end, token_address=token_address,
            )
            return transfers, end
        except Web3RPCError as exc:
            if span <= _MIN_SCAN_RANGE:
                logger.error(
                    "scan_from_cursor exhausted adaptive range: "
                    "start=%s end=%s span=%s addresses=%s err=%r",
                    start, end, span, len(addresses), exc,
                )
                raise
            logger.warning(
                "scan_from_cursor range rejected — halving span: "
                "start=%s end=%s span=%s addresses=%s err=%r",
                start, end, span, len(addresses), exc,
            )
            span = max(span // 2, _MIN_SCAN_RANGE)
        except (ClientError, ConnectionError, TimeoutError) as exc:
            logger.error(
                "scan_from_cursor transport failure (range not at fault): "
                "start=%s end=%s span=%s addresses=%s err=%r",
                start, end, span, len(addresses), exc,
            )
            raise
