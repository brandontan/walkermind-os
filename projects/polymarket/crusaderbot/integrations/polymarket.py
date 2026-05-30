"""Polymarket Gamma + CLOB clients (cached, retry-wrapped) + on-chain CTF redemption."""
from __future__ import annotations

import json
import time
from typing import Any, Optional

import httpx
import structlog
from tenacity import (
    AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential,
)

from ..cache import get_cache, set_cache
from ..config import get_settings
from .clob.rate_limiter import RateLimiter

log = structlog.get_logger(__name__)

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
DATA_API = "https://data-api.polymarket.com"

# Module-level rate limiters for outbound read traffic.
# Gamma public API: 100 req/min documented limit → 5 RPS steady-state with
# burst of 10 absorbs scan bursts without tripping 429s.
# CLOB read endpoints share the same 10 RPS budget as the write adapter so
# combined read+write traffic stays within the per-account limit.
_gamma_limiter = RateLimiter(rps=5.0, burst=10.0)
_clob_read_limiter = RateLimiter(rps=10.0, burst=10.0)

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
    # Throttle before each attempt so retries also respect the rate limit.
    if url.startswith(CLOB):
        await _clob_read_limiter.acquire()
    else:
        await _gamma_limiter.acquire()
    async for attempt in _retry():
        with attempt:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.get(url, params=params)
                r.raise_for_status()
                return r.json()


async def get_markets(category: Optional[str] = None,
                      limit: int = 100,
                      order: Optional[str] = None,
                      ascending: Optional[bool] = None,
                      end_date_max: Optional[str] = None) -> list[dict]:
    """Active markets list (Gamma). Cached 5 min.

    Optional Gamma query params surface a wider, fresher universe for the
    signal scanner:
      * ``order``        — sort field (e.g. ``"volume24hr"``, ``"liquidity"``).
      * ``ascending``    — sort direction; pair with ``order``.
      * ``end_date_max`` — ISO timestamp upper bound on resolution date, so
                           far-dated futures (championship winners months out)
                           are excluded server-side.
    Defaults (all None) preserve the prior behaviour for existing callers.
    """
    key = f"mkts:{category or 'all'}:{limit}:{order or '-'}:{ascending}:{end_date_max or '-'}"
    if hit := await get_cache(key):
        return hit
    params: dict[str, Any] = {"active": "true", "closed": "false", "limit": limit}
    if category:
        params["tag"] = category
    if order:
        params["order"] = order
    if ascending is not None:
        params["ascending"] = "true" if ascending else "false"
    if end_date_max:
        params["end_date_max"] = end_date_max
    try:
        data = await _get_json(f"{GAMMA}/markets", params=params)
        if isinstance(data, dict):
            data = data.get("data", [])
        await set_cache(key, data, ttl=300)
        return data or []
    except Exception as exc:
        log.warning("get_markets failed", err=str(exc))
        return []


async def get_events_with_markets(limit: int = 200) -> list[dict]:
    """Fetch active Gamma events and flatten to category-annotated market dicts.

    Gamma ``/markets`` dicts carry no category or tag data — only a
    ``groupItemTitle`` (market-specific description) and ``slug`` (event slug),
    so substring matching against dashboard categories (Politics/Sports/Crypto/
    Finance/…) fails for almost every filter selection.

    This function uses the ``/events`` endpoint, which carries a ``tags`` array
    (e.g. ``["Crypto", "Finance", "Business"]``) at the event level.  Each
    market in ``event.markets`` is returned with a ``category`` key set to the
    lowercase space-joined tag labels of the parent event, enabling
    ``_filter_markets_by_category`` to match reliably.
    """
    key = f"events_with_markets:{limit}"
    if hit := await get_cache(key):
        return hit
    params: dict[str, Any] = {"active": "true", "closed": "false", "limit": limit}
    try:
        events = await _get_json(f"{GAMMA}/events", params=params)
        if isinstance(events, dict):
            events = events.get("data", [])
        result: list[dict] = []
        for event in (events or []):
            # Build category from event tags, skipping the generic "All" tag.
            tag_labels = [
                t["label"].strip()
                for t in (event.get("tags") or [])
                if t.get("slug") != "all" and t.get("label", "").strip()
            ]
            category = " ".join(tag_labels).lower()
            if not category:
                category = (event.get("category") or "").strip().lower()
            for m in (event.get("markets") or []):
                result.append({**m, "category": category})
        await set_cache(key, result, ttl=300)
        return result
    except Exception as exc:
        log.warning("get_events_with_markets failed", err=str(exc))
        return []


async def get_crypto_short_markets(limit: int = 500) -> list[dict]:
    """Fetch the freshest active markets, ordered newest-created first.

    Retained for callers that want a broad recent-market snapshot. For the
    crypto-short presets prefer ``get_crypto_window_markets`` which targets the
    exact currently-live candle window deterministically.
    """
    key = f"crypto_short:{limit}"
    if hit := await get_cache(key):
        return hit
    params: dict[str, Any] = {
        "active": "true",
        "closed": "false",
        "limit": limit,
        "order": "startDate",
        "ascending": "false",
    }
    try:
        data = await _get_json(f"{GAMMA}/markets", params=params)
        if isinstance(data, dict):
            data = data.get("data", [])
        data = data or []
        await set_cache(key, data, ttl=60)
        return data
    except Exception as exc:
        log.warning("get_crypto_short_markets failed", err=str(exc))
        return []


_TF_WINDOW_SECONDS: dict[str, int] = {"5m": 300, "15m": 900}

# Cache TTL for the candle-window market LIST. The set of markets in a window is
# stable for the whole window (only prices move, which the scanner re-reads from
# the CLOB separately), so a slightly longer TTL cuts the /events poll volume
# (4 coins x 2 slots every scan tick) without staling entry timing — a hedge
# against the high-frequency polling that can get the bot IP throttled by Gamma.
_CRYPTO_WINDOW_CACHE_TTL: int = 45


# Crypto candle assets that are MONITOR-ONLY (not tradeable). Mirror of
# services/signal_scan/signal_scan_job._MONITOR_ONLY_ASSETS (lowercased here for
# slug construction). These are observed for 30-day edge stats via a separate
# market_data path but must NEVER be fetched as a tradeable candle window — a
# window here feeds the trade engine. Keep in sync when an asset graduates
# to / from monitor-only. (ref WARP/ROOT/prelaunch-system-audit F3.)
_DEFAULT_TRADEABLE_COINS: tuple[str, ...] = ("btc", "eth", "sol")
_MONITOR_ONLY_COINS: frozenset[str] = frozenset({"bnb"})


def _resolve_tradeable_coins(
    assets: "list[str] | tuple[str, ...] | None",
) -> list[str]:
    """Resolve UI tickers to lowercase tradeable candle coins.

    Empty / None defaults to the tradeable set (BTC/ETH/SOL). Monitor-only
    assets (BNB) are ALWAYS excluded — even from an explicit ``assets`` list —
    so a candle window for a non-tradeable asset can never reach the trade
    engine. Closes WARP/ROOT/prelaunch-system-audit F3 (the BNB default-asset
    fallback that reintroduced BNB whenever ``assets`` was empty/None).
    """
    # A bare string is iterable char-by-char — wrap it as a single ticker so
    # "BTC" resolves to ["btc"], not ["b", "t", "c"].
    if isinstance(assets, str):
        assets = [assets]
    requested = [str(a).strip().lower() for a in (assets or [])]
    coins = requested or list(_DEFAULT_TRADEABLE_COINS)
    return [c for c in coins if c and c not in _MONITOR_ONLY_COINS]


async def get_crypto_window_markets(
    timeframe: str,
    assets: "list[str] | tuple[str, ...] | None" = None,
    *,
    include_next: bool = True,
) -> list[dict]:
    """Fetch the currently-live crypto up/down candle markets by exact slug.

    Polymarket's recurring candle markets encode their resolution window in the
    slug: ``{coin}-updown-{tf}-{slot}`` where ``slot = now // step * step`` and
    ``step`` is 300s (5m) or 900s (15m). Computing the slug directly targets the
    market resolving in the *current* window (and, with ``include_next``, the
    following one) — the ones with real in-window liquidity and a live CLOB book.
    A broad list fetch buries these among thousands of markets, which is why the
    scanner never saw them.

    ``assets`` are UI tickers; empty/None defaults to the tradeable set
    (BTC/ETH/SOL). Monitor-only assets (e.g. BNB) are always excluded — they
    must never be fetched as a tradeable candle window. Each returned market
    dict is annotated ``category="crypto"`` so downstream eligibility passes.
    Returns [] on any failure. Cached 20s (the live window for a 5-minute
    candle is itself only minutes long).
    """
    step = _TF_WINDOW_SECONDS.get(timeframe)
    if step is None:
        return []
    coins = _resolve_tradeable_coins(assets)
    if not coins:
        return []
    now = int(time.time())
    slot = now // step * step
    slots = [slot, slot + step] if include_next else [slot]

    key = f"crypto_window:{timeframe}:{','.join(sorted(coins))}:{slot}:{include_next}"
    if hit := await get_cache(key):
        return hit

    out: list[dict] = []
    seen: set[str] = set()
    attempted = 0
    fetch_errors = 0
    for coin in coins:
        for s in slots:
            slug = f"{coin}-updown-{timeframe}-{s}"
            attempted += 1
            try:
                events = await _get_json(f"{GAMMA}/events", params={"slug": slug})
            except Exception as exc:
                fetch_errors += 1
                # WARNING, not debug: a persistent failure here silently starves
                # the candle scanner of markets. The 2026-05-29 incident ran ~14h
                # with zero close_sweep/safe_close/flip_hunter trades precisely
                # because this was logged at debug and invisible to monitoring.
                log.warning(
                    "get_crypto_window_markets slug fetch failed",
                    slug=slug, err=str(exc),
                )
                continue
            if isinstance(events, dict):
                events = events.get("data", [])
            for event in (events or []):
                for m in (event.get("markets") or []):
                    mid = str(m.get("id") or m.get("conditionId") or slug)
                    if mid in seen:
                        continue
                    seen.add(mid)
                    out.append({**m, "category": "crypto"})
    # Loud signal when the WHOLE candle universe came back empty because every
    # fetch errored (vs a legitimately marketless gap, which has 0 errors) — this
    # is the condition that must page the operator, not vanish silently.
    if not out and fetch_errors:
        log.warning(
            "get_crypto_window_markets empty — all candle fetches failed",
            timeframe=timeframe, attempted=attempted, fetch_errors=fetch_errors,
        )
    await set_cache(key, out, ttl=_CRYPTO_WINDOW_CACHE_TTL)
    return out


async def get_market(market_id: str) -> Optional[dict]:
    """Fetch a single market from Gamma API by conditionId. Cached 2 min.

    Resolves via ``GET /markets?condition_ids={id}`` (the plural filter param).
    The singular ``conditionId`` form is SILENTLY IGNORED by Gamma — it returns
    the default market list (first row regardless of the id), so resolution
    detection was reading an unrelated market and never observed a real close.
    The returned row's conditionId is validated against ``market_id`` before
    caching so a mismatched/ignored filter can never settle a position against
    the wrong market.

    Returns None when the id is not individually indexed under ``/markets``
    (e.g. recurring crypto up/down candle markets, which live only under
    ``/events`` — callers fall back to ``get_event_market_by_slug``).
    """
    key = f"mkt:{market_id}"
    if hit := await get_cache(key):
        return hit
    try:
        data = await _get_json(f"{GAMMA}/markets", params={"condition_ids": market_id})
    except Exception as exc:
        log.warning("get_market failed", market_id=market_id, err=str(exc))
        return None
    markets: list = data if isinstance(data, list) else data.get("data", [])
    result = next(
        (
            m
            for m in markets
            if isinstance(m, dict)
            and str(m.get("conditionId") or m.get("condition_id") or "") == str(market_id)
        ),
        None,
    )
    if result is None:
        return None
    await set_cache(key, result, ttl=120)
    return result


async def get_event_market_by_slug(slug: str) -> Optional[dict]:
    """Resolve a recurring/event market (e.g. crypto up/down candles) by slug.

    Crypto candle markets are NOT individually indexed under ``/markets``
    (``condition_ids`` returns empty), so resolution detection must read the
    nested market from ``GET /events?slug={slug}``. Returns the nested market
    dict whose slug matches (or the event's sole market as a fallback), or
    None. Not cached — resolution polling needs the fresh ``closed`` flag.
    """
    if not slug:
        return None
    try:
        events = await _get_json(f"{GAMMA}/events", params={"slug": slug})
    except Exception as exc:
        log.warning("get_event_market_by_slug failed", slug=slug, err=str(exc))
        return None
    if isinstance(events, dict):
        events = events.get("data", [])
    for event in (events or []):
        markets = event.get("markets") or []
        for m in markets:
            if isinstance(m, dict) and str(m.get("slug") or "") == slug:
                return m
        if markets and isinstance(markets[0], dict):
            return markets[0]
    return None



async def get_market_by_slug(slug: str) -> Optional[dict]:
    """Fetch a single active market by slug from Gamma API. Cached 2 min."""
    key = f"mktslug:{slug}"
    if hit := await get_cache(key):
        return hit
    try:
        data = await _get_json(f"{GAMMA}/markets", params={"slug": slug})
        markets: list = data if isinstance(data, list) else data.get("data", [])
        result = markets[0] if markets else None
        if result:
            await set_cache(key, result, ttl=120)
        return result
    except Exception as exc:
        log.warning("get_market_by_slug failed", slug=slug, err=str(exc))
        return None


async def get_live_market_price(market_id: str, side: str) -> Optional[float]:
    """Fetch live mid-price for one side of a binary market.

    Resolves market via ``GET /markets?condition_ids={market_id}`` (the plural
    filter param). The singular ``conditionId`` form is SILENTLY IGNORED by Gamma
    — it returns the default market list (first row = unrelated market), so TP/SL
    evaluations and P&L were pricing positions against the WRONG market.
    The returned row's conditionId is validated before caching to prevent stale
    mismatched data from persisting. Primary price source: CLOB
    ``GET /price?token_id=...&side=buy`` (live order book). Fallback: Gamma
    ``outcomePrices[0]`` (YES) / ``[1]`` (NO).

    Cache key ``lp:{market_id}`` is shared across sides — one HTTP round-trip
    per market per 30 s tick, regardless of how many positions share the market.
    Returns None on any error — callers fall back to ``entry_price``.
    """
    cache_key = f"lp:{market_id}"
    if hit := await get_cache(cache_key):
        market_data: dict = hit
    else:
        try:
            # condition_ids (plural) is the correct filter param — see get_market().
            # The singular conditionId= is silently ignored by Gamma.
            data = await _get_json(
                f"{GAMMA}/markets",
                params={"condition_ids": market_id},
                timeout=5.0,
            )
        except Exception as exc:
            log.warning("get_live_market_price fetch failed", market_id=market_id, err=str(exc))
            return None
        markets: list = data if isinstance(data, list) else data.get("data", [])
        if not markets or not isinstance(markets[0], dict):
            log.warning("get_live_market_price no market found", condition_id=market_id)
            return None
        market_data = markets[0]
        # Validate conditionId when present — reject if it doesn't match the
        # requested id to prevent caching data from a mismatched market.
        # When the returned market has no conditionId field (thin API responses),
        # we accept it; Gamma always includes conditionId on real markets.
        returned_cid = str(
            market_data.get("conditionId") or market_data.get("condition_id") or ""
        )
        if returned_cid and returned_cid != str(market_id):
            log.warning("get_live_market_price conditionId mismatch", requested=market_id, returned=returned_cid)
            return None
        await set_cache(cache_key, market_data, ttl=30)

    # Primary: CLOB /price — live order-book mid-price is more accurate than
    # Gamma outcomePrices for TP/SL evaluation.
    # tokens[0]=YES, tokens[1]=NO per Polymarket convention.
    token_idx = 0 if side == "yes" else 1
    tokens: list = market_data.get("tokens") or []
    token_id: Optional[str] = None
    if len(tokens) > token_idx and isinstance(tokens[token_idx], dict):
        token_id = tokens[token_idx].get("token_id")

    if token_id:
        try:
            clob_resp = await _get_json(
                f"{CLOB}/price",
                params={"token_id": token_id, "side": "buy"},
                timeout=5.0,
            )
            if isinstance(clob_resp, dict):
                raw_clob = clob_resp.get("price")
                if raw_clob is not None:
                    clob_price = float(raw_clob)
                    # CLOB /price returns the degenerate sentinels 1.0 (no
                    # asks) / 0.0 (no bids) when that side of the book is
                    # empty — common on thin longshot markets. Treating that
                    # as a live mark prices an open 5.5c position as if it
                    # resolved at $1.00, producing the +900% P&L bug. Accept
                    # only a strictly-interior price; otherwise fall through
                    # to the Gamma outcomePrices last-trade fallback.
                    if 0.0 < clob_price < 1.0:
                        return clob_price
                    log.warning(
                        "get_live_market_price CLOB empty-book sentinel — falling back to Gamma",
                        price=clob_price, market_id=market_id, side=side,
                    )
        except Exception as exc:
            log.warning("get_live_market_price CLOB price failed", market_id=market_id, side=side, err=str(exc))

    # Fallback: Gamma outcomePrices[0]=YES [1]=NO.
    # Gamma returns outcomePrices as a JSON-encoded string e.g. '["0.565","0.435"]'.
    outcomes = market_data.get("outcomePrices") or market_data.get("outcome_prices") or []
    if isinstance(outcomes, str):
        try:
            outcomes = json.loads(outcomes)
        except Exception:
            outcomes = []

    idx = 0 if side == "yes" else 1
    try:
        raw = outcomes[idx]
        if raw is None:
            return None
        price = float(raw)
        # Strictly-interior only: exactly 0.0/1.0 is the settled outcome
        # value, not a live tradeable mark for a still-open position.
        # Returning None here makes callers fall back to entry_price
        # (unrealised P&L == 0 / "N/A") instead of a 1.0-inflated figure.
        if not (0.0 < price < 1.0):
            log.warning("get_live_market_price out-of-range price", price=price, market_id=market_id, side=side)
            return None
        return price
    except (IndexError, TypeError, ValueError) as exc:
        log.warning("get_live_market_price parse error", market_id=market_id, side=side, err=str(exc))
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
        log.warning("get_book failed", token_id=token_id, err=str(exc))
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
        log.warning("get_user_activity failed", wallet=wallet_address, err=str(exc))
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
    from .polygon import _get_w3, gas_price_gwei, nonce_lock
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

    # Gas-price ceiling — parity with transfer_usdc/sweep so a fee spike can't
    # drain the hot pool on redemption gas.
    gwei = await gas_price_gwei()
    if gwei > settings.INSTANT_REDEEM_GAS_GWEI_MAX:
        raise RuntimeError(
            f"submit_live_redemption blocked: gas {gwei:.1f} gwei exceeds ceiling "
            f"{settings.INSTANT_REDEEM_GAS_GWEI_MAX:.1f}"
        )

    # Serialize nonce read → sign → broadcast against other master-wallet sends.
    async with nonce_lock(addr_cs):
        nonce = await w3.eth.get_transaction_count(addr_cs, "pending")
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
