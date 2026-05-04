"""Polymarket Gamma + CLOB clients (cached, retry-wrapped) + on-chain CTF redemption."""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx
from tenacity import (
    AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential,
)

from ..cache import get_cache, set_cache
from ..config import get_settings

logger = logging.getLogger(__name__)

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
DATA_API = "https://data-api.polymarket.com"

# Gnosis ConditionalTokens contract used by Polymarket on Polygon mainnet.
# Source: docs.polymarket.com — required for redeemPositions().
CTF_CONTRACT_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"

CTF_REDEEM_ABI: list[dict[str, Any]] = [
    {
        "inputs": [
            {"name": "collateralToken", "type": "address"},
            {"name": "parentCollectionId", "type": "bytes32"},
            {"name": "conditionId", "type": "bytes32"},
            {"name": "indexSets", "type": "uint256[]"},
        ],
        "name": "redeemPositions",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]


def _retry():
    return AsyncRetrying(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
    )


async def _get_json(url: str, params: dict | None = None,
                    timeout: float = 10.0) -> Any:
    async for attempt in _retry():
        with attempt:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.get(url, params=params)
                r.raise_for_status()
                return r.json()


async def get_markets(category: Optional[str] = None,
                      limit: int = 100) -> list[dict]:
    """Active markets list (Gamma). Cached 5 min."""
    key = f"mkts:{category or 'all'}:{limit}"
    if hit := await get_cache(key):
        return hit
    params: dict[str, Any] = {"active": "true", "closed": "false", "limit": limit}
    if category:
        params["tag"] = category
    try:
        data = await _get_json(f"{GAMMA}/markets", params=params)
        if isinstance(data, dict):
            data = data.get("data", [])
        await set_cache(key, data, ttl=300)
        return data or []
    except Exception as exc:
        logger.warning("get_markets failed: %s", exc)
        return []


async def get_market(market_id: str) -> Optional[dict]:
    key = f"mkt:{market_id}"
    if hit := await get_cache(key):
        return hit
    try:
        data = await _get_json(f"{GAMMA}/markets/{market_id}")
        await set_cache(key, data, ttl=120)
        return data
    except Exception as exc:
        logger.warning("get_market %s failed: %s", market_id, exc)
        return None


async def get_book(token_id: str) -> dict:
    """Order book (CLOB). Cached 30s."""
    key = f"book:{token_id}"
    if hit := await get_cache(key):
        return hit
    try:
        data = await _get_json(f"{CLOB}/book", params={"token_id": token_id},
                               timeout=5.0)
        await set_cache(key, data, ttl=30)
        return data
    except Exception as exc:
        logger.warning("get_book %s failed: %s", token_id, exc)
        return {"bids": [], "asks": []}


async def get_user_activity(wallet_address: str, limit: int = 20) -> list[dict]:
    """Recent trades for a wallet — used by copy-trade scanner."""
    key = f"act:{wallet_address}:{limit}"
    if hit := await get_cache(key):
        return hit
    try:
        data = await _get_json(
            f"{DATA_API}/activity",
            params={"user": wallet_address, "limit": limit, "type": "TRADE"},
            timeout=10.0,
        )
        if isinstance(data, dict):
            data = data.get("data", [])
        await set_cache(key, data or [], ttl=60)
        return data or []
    except Exception as exc:
        logger.warning("get_user_activity %s failed: %s", wallet_address, exc)
        return []


# ----- LIVE order submission (only used by live execution engine) -----

def _build_clob_client():
    """Construct py-clob-client from settings + master wallet PK."""
    from ..wallet.vault import master_wallet
    settings = get_settings()
    if not (settings.POLYMARKET_API_KEY and settings.POLYMARKET_API_SECRET
            and settings.POLYMARKET_PASSPHRASE):
        raise RuntimeError("Polymarket API credentials not configured.")
    try:
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import ApiCreds
    except Exception as exc:
        raise RuntimeError(f"py-clob-client unavailable: {exc}") from exc
    _, pk = master_wallet()
    creds = ApiCreds(
        api_key=settings.POLYMARKET_API_KEY,
        api_secret=settings.POLYMARKET_API_SECRET,
        api_passphrase=settings.POLYMARKET_PASSPHRASE,
    )
    return ClobClient(CLOB, key=pk, chain_id=137, creds=creds)


class PreparedLiveOrder:
    """Locally-built and signed CLOB order. No network call has been made."""
    __slots__ = ("client", "signed")

    def __init__(self, client, signed) -> None:
        self.client = client
        self.signed = signed


def prepare_live_order(token_id: str, side: str, shares: float,
                       price: float) -> PreparedLiveOrder:
    """LOCAL phase: construct + sign the CLOB order. NO network I/O.

    Any exception raised here is a *definite pre-submit* failure and is
    safe for the router to paper-fall-back on.
    """
    from py_clob_client.clob_types import OrderArgs
    client = _build_clob_client()
    order_args = OrderArgs(
        token_id=token_id,
        price=price,
        size=shares,
        side=side.upper(),
    )
    signed = client.create_order(order_args)
    return PreparedLiveOrder(client=client, signed=signed)


async def submit_signed_live_order(prepared: PreparedLiveOrder) -> dict:
    """NETWORK phase: POST the signed order to the broker.

    Any exception raised here MUST be treated as *post-submit ambiguous*
    by the caller — a network error after the broker received the request
    cannot be distinguished from a clean rejection without reconciliation.
    The caller is responsible for marking the order 'unknown' and refusing
    paper-fallback (per LivePostSubmitError contract).

    Tenacity wraps transient HTTP errors so a single dropped packet is
    retried, but persistent failures raise.
    """
    import asyncio
    from py_clob_client.clob_types import OrderType

    def _sync_post() -> dict:
        return prepared.client.post_order(prepared.signed, OrderType.GTC)

    async for attempt in _retry():
        with attempt:
            return await asyncio.to_thread(_sync_post)
    raise RuntimeError("submit_signed_live_order: unreachable")


async def submit_live_order(token_id: str, side: str, shares: float,
                            price: float) -> dict:
    """Convenience wrapper for callers that don't need the prepare/submit split.

    NOTE: callers that care about pre-vs-post-submit safety classification
    (e.g. live.execute) MUST use prepare_live_order + submit_signed_live_order
    explicitly so they can attribute the failure correctly.
    """
    prepared = prepare_live_order(token_id, side, shares, price)
    return await submit_signed_live_order(prepared)


async def submit_live_redemption(condition_id: str) -> dict:
    """Submit on-chain CTF redeemPositions() for a resolved binary market.

    Acts on the master (hot-pool) wallet that holds all user CTF tokens.
    Both index sets [1, 2] are passed so any held YES *and* NO tokens for
    the condition are redeemed in one tx (losing-side tokens redeem to 0,
    winning-side tokens redeem to 1 USDC each).

    Gated behind EXECUTION_PATH_VALIDATED so this never fires until the
    operator has hand-validated the path.

    Returns: {tx_hash, gas_used, status}.
    """
    settings = get_settings()
    if not settings.EXECUTION_PATH_VALIDATED:
        raise RuntimeError(
            "submit_live_redemption blocked: EXECUTION_PATH_VALIDATED=false"
        )
    from web3 import AsyncWeb3
    from .polygon import _get_w3
    from ..wallet.vault import master_wallet

    w3 = _get_w3()
    addr, pk = master_wallet()
    addr_cs = AsyncWeb3.to_checksum_address(addr)

    cond_hex = condition_id if condition_id.startswith("0x") else f"0x{condition_id}"
    if len(cond_hex) != 66:
        raise RuntimeError(f"invalid condition_id length: {cond_hex!r}")
    cond_bytes = bytes.fromhex(cond_hex[2:])
    parent_collection = b"\x00" * 32
    usdc_cs = AsyncWeb3.to_checksum_address(settings.USDC_POLYGON)
    ctf = w3.eth.contract(
        address=AsyncWeb3.to_checksum_address(CTF_CONTRACT_ADDRESS),
        abi=CTF_REDEEM_ABI,
    )

    nonce = await w3.eth.get_transaction_count(addr_cs)
    gas_price = await w3.eth.gas_price
    tx = await ctf.functions.redeemPositions(
        usdc_cs, parent_collection, cond_bytes, [1, 2],
    ).build_transaction({
        "from": addr_cs,
        "nonce": nonce,
        "gas": 350000,
        "gasPrice": gas_price,
        "chainId": 137,
    })
    signed = w3.eth.account.sign_transaction(tx, private_key=pk)
    raw = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction")
    tx_hash = await w3.eth.send_raw_transaction(raw)
    receipt = await w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
    status = int(receipt["status"])
    if status != 1:
        raise RuntimeError(
            f"redeemPositions reverted (tx={tx_hash.hex()}, condition={cond_hex})"
        )
    return {
        "tx_hash": tx_hash.hex(),
        "gas_used": int(receipt["gasUsed"]),
        "status": status,
    }
