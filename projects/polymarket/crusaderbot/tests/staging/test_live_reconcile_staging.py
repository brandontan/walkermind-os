"""WARP-74 Lane 2 — live-broker staging proof harness (the final pre-LIVE gate).

The three P0 reconcile gaps are coded + merged (#1613) and proven HERMETICALLY in
``tests/test_live_reconcile.py`` (fake pool + fake broker). This module proves the
SAME logic against a REAL Polymarket CLOB broker on an isolated staging wallet —
the one thing fakes cannot show: that a broker ``cancel_all`` actually pulls a
resting GTC order off-chain, that ``get_open_orders`` truth drives adoption, and
that the drift detector sees a real orphan.

Polymarket runs only on Polygon mainnet (no testnet exists), so the proof uses an
ISOLATED THROWAWAY wallet with minimal USDC and TINY orders. The whole module is
guarded by ``STAGING_WALLET_KEY``: with no wallet provisioned every test SKIPS —
it never touches the network, the broker, or a database, so it is inert in CI.

Five acceptance cases (full operator procedure: docs/runbooks/warp74-staging-proof.md):

  1. crash-mid-close   — reconcile_closing_positions: rollback / page-no-id /
                         (finalize-once, page-partial — fill-gated, see below)
  2. unknown-order     — reconcile_live_orders: adopt-on-match / page-mismatch /
                         halt-on-ambiguous, all against REAL resting orders
  3. kill cancel-all   — execute_kill_switch broker-cancels a REAL resting GTC
                         BEFORE the DB write; get_open_orders confirms it is gone
  4. drift detect      — detect_order_drift surfaces a REAL broker-only orphan +
                         a DB-only id, mutating NOTHING
  5. infra-degraded    — router falls back to PAPER and emits LIVE INFRA DEGRADED

SAFETY (enforced here, restated in the runbook):
  * NEVER run against the prod Fly app / prod Supabase — point a SEPARATE staging
    app's env at this. The DB side is a recording in-memory fake (no real DB
    writes at all), so only the BROKER is real.
  * Fill-dependent sub-cases (finalize-once / page-partial) burn real USDC on a
    market order and so are additionally gated by ``STAGING_ALLOW_FILLS=1``.
  * Every test cancels all of its own resting orders on teardown — no shared state.
"""
from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any, Optional
from uuid import uuid4

import pytest
import pytest_asyncio

from projects.polymarket.crusaderbot.domain.execution import drift_detector as dd
from projects.polymarket.crusaderbot.domain.execution import live_reconcile as lr
from projects.polymarket.crusaderbot.domain.risk import kill_switch_exec as kse
from projects.polymarket.crusaderbot.integrations.clob import (
    ensure_clob_credentials,
    get_clob_breaker,
    get_clob_client,
    get_clob_rate_limiter,
)
from projects.polymarket.crusaderbot.integrations import clob as _clob_mod
from projects.polymarket.crusaderbot.integrations.clob.adapter import ClobAdapter
from projects.polymarket.crusaderbot.integrations.clob.exceptions import ClobAuthError

# --- staging guard ------------------------------------------------------------
_WALLET = os.getenv("STAGING_WALLET_KEY")
_ALLOW_FILLS = os.getenv("STAGING_ALLOW_FILLS") == "1"

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not _WALLET,
        reason="staging wallet not provisioned (set STAGING_WALLET_KEY to run)",
    ),
]

# Market coordinates for the resting-order cases. The bot trades short-lived
# RECURRING markets (5m/15m crypto up/down) whose token_ids resolve and roll over
# every few minutes, so pinning STAGING_TOKEN_ID/STAGING_MARKET_ID in repo secrets
# is unworkable -- they go stale before a run ever starts. They are therefore
# OPTIONAL OVERRIDES: when unset (the default), a currently-OPEN market is resolved
# AT RUNTIME by ``_resolve_open_market`` via the public, unauthenticated CLOB read
# API (no secret, no Redis). Set BOTH only to reproduce a specific market; when set,
# STAGING_TOKEN_ID must be the BUY-side token of a market trading well above
# STAGING_REST_PRICE so a BUY there RESTS (never fills). STAGING_MARKET_ID is its
# condition id. These globals may be reassigned by _ensure_market_resolved().
_TOKEN = os.getenv("STAGING_TOKEN_ID", "")
_MARKET = os.getenv("STAGING_MARKET_ID", "")
_NO_TOKEN = os.getenv("STAGING_NO_TOKEN_ID", "")
_REST_PRICE = float(os.getenv("STAGING_REST_PRICE", "0.10"))   # far below market
_SHARES = float(os.getenv("STAGING_ORDER_SHARES", "12"))        # ~ $1.20 notional
_TICK = os.getenv("STAGING_TICK_SIZE", "0.01")
_NEG_RISK = os.getenv("STAGING_NEG_RISK", "false").lower() in ("1", "true", "yes")

_BROKER_ID_KEYS = ("orderID", "order_id", "id", "orderId")

# Cache of the runtime-resolved market so the network lookup runs at most once.
_RESOLVED: dict[str, Any] = {}


def _need_market() -> None:
    if not (_TOKEN and _MARKET):
        pytest.skip("no open market resolved/overridden for broker cases")


def _parse_json_list(v: Any) -> list:
    """Gamma encodes ``clobTokenIds``/``outcomePrices`` as JSON STRINGS (e.g.
    '["123","456"]') on most fields, but occasionally as real lists. Accept both."""
    import json as _json
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        try:
            out = _json.loads(v)
            return out if isinstance(out, list) else []
        except (ValueError, TypeError):
            return []
    return []


async def _resolve_open_market() -> dict[str, Any]:
    """Pick a tradable, currently-OPEN market for the resting-order cases.

    No stale secret required. Source is the Gamma API ``/markets`` with
    ``active=true&closed=false`` ordered by 24h volume — this returns LIQUID, OPEN
    markets directly (the CLOB ``/markets`` cursor endpoint has no active filter and
    pages over the entire historical, mostly-closed set, so it surfaces nothing
    usable). Criteria: order-book enabled, accepting orders, exactly two binary
    tokens, NOT neg-risk (keeps the proof on the standard exchange contract), and a
    BUY-side token priced comfortably above ``_REST_PRICE`` so the test order RESTS
    rather than crosses. The chosen token's CLOB ``/book`` is then verified to carry
    an ask above the resting price before the market is accepted.
    """
    import httpx

    from projects.polymarket.crusaderbot.integrations.clob.market_data import (
        MarketDataClient,
    )

    floor = _REST_PRICE + 0.05   # required headroom: best ask must exceed this
    params = {
        "active": "true", "closed": "false", "limit": "500",
        "order": "volume24hr", "ascending": "false",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            resp = await http.get(
                "https://gamma-api.polymarket.com/markets", params=params)
            resp.raise_for_status()
            rows = resp.json()
    except Exception as exc:  # noqa: BLE001 — surface a clear, actionable error
        raise RuntimeError(
            f"staging proof could not reach Gamma /markets to resolve an open "
            f"market ({type(exc).__name__}: {exc}). If the run region is geoblocked, "
            f"pin STAGING_TOKEN_ID + STAGING_MARKET_ID with pin_market=true."
        ) from exc
    if isinstance(rows, dict):
        rows = rows.get("data") or rows.get("markets") or []

    # Build (market, buy_token, no_token, buy_price) tuples for binary, open,
    # order-book-enabled, non-neg-risk markets, BUYing the higher-priced outcome.
    candidates: list[tuple[dict, str, str, float]] = []
    for m in (rows or []):
        if not isinstance(m, dict):
            continue
        if m.get("closed") or not m.get("active"):
            continue
        # Only an EXPLICIT False excludes -- a missing/renamed flag must not zero
        # out the universe; the real gate is the /book verification below.
        if m.get("enableOrderBook") is False or m.get("acceptingOrders") is False:
            continue
        if m.get("negRisk"):
            continue
        toks = _parse_json_list(m.get("clobTokenIds"))
        prices = _parse_json_list(m.get("outcomePrices"))
        cond = m.get("conditionId") or ""
        if len(toks) != 2 or len(prices) != 2 or not cond:
            continue
        try:
            p = [float(x) for x in prices]
        except (TypeError, ValueError):
            continue
        idx = 0 if p[0] >= p[1] else 1               # BUY the higher-priced side
        buy_val, no_val = toks[idx], toks[1 - idx]
        if not buy_val or not no_val:                 # guard None/empty (str(None)="None")
            continue
        buy_tok, no_tok, price = str(buy_val), str(no_val), p[idx]
        if price < floor + 0.05:                      # need headroom above the rest price
            continue
        candidates.append((m, buy_tok, no_tok, price))

    # Volume order already favours liquidity; among those, prefer the longest-dated
    # so the book can't resolve mid-test.
    candidates.sort(key=lambda c: str(c[0].get("endDate") or ""), reverse=True)

    async with MarketDataClient() as md:
        for m, buy_tok, no_tok, _price in candidates:
            try:
                book = await md.get_orderbook(buy_tok)
                ask_prices = [
                    float(a["price"]) for a in (book.get("asks") or [])
                    if isinstance(a, dict) and a.get("price")
                ]
            except Exception:  # noqa: BLE001 — thin/absent/malformed book: skip it
                continue
            if not ask_prices or min(ask_prices) <= floor:
                continue
            return {
                "token": buy_tok,
                "market": str(m["conditionId"]),
                "no_token": no_tok,
                "tick": str(m.get("orderPriceMinTickSize") or _TICK),
                "neg_risk": False,
            }

    raise RuntimeError(
        "staging proof could not resolve any open, order-book-enabled market with "
        "an ask above the resting price -- Gamma /markets returned no eligible "
        "candidate (network/region issue or an unusually thin market universe). "
        "Pin STAGING_TOKEN_ID + STAGING_MARKET_ID + pin_market=true to override."
    )


async def _ensure_market_resolved() -> None:
    """Populate the market-coordinate globals once, honouring an env override."""
    if _TOKEN and _MARKET:
        return
    if not _RESOLVED:
        _RESOLVED.update(await _resolve_open_market())
    g = globals()
    g["_TOKEN"] = _RESOLVED["token"]
    g["_MARKET"] = _RESOLVED["market"]
    if _RESOLVED.get("no_token"):
        g["_NO_TOKEN"] = _RESOLVED["no_token"]
    g["_TICK"] = _RESOLVED["tick"]
    g["_NEG_RISK"] = _RESOLVED["neg_risk"]


def _broker_id(o: dict[str, Any]) -> str:
    for k in _BROKER_ID_KEYS:
        if o.get(k):
            return str(o[k])
    return ""


# --- real staging CLOB client -------------------------------------------------
def _staging_settings() -> Any:
    """A real-CLOB Settings copy bound to the isolated staging wallet.

    Built off the live Settings so every unrelated default is inherited, then
    overridden to point at the throwaway wallet. API creds are taken from
    STAGING_* env if present, else auto-derived from the private key at runtime.
    """
    from projects.polymarket.crusaderbot.config import get_settings

    # CLOB v2 migration: the proof validates the polymarket-client backend by
    # default (USE_PYSDK_CLOB unset/1); set USE_PYSDK_CLOB=0 to fall back to the
    # legacy py-clob-client backend for a comparison run.
    _use_pysdk = os.getenv("USE_PYSDK_CLOB", "1").strip().lower() not in (
        "0", "false", "no", "",
    )
    return get_settings().model_copy(update={
        "USE_REAL_CLOB": True,
        "USE_PYSDK_CLOB": _use_pysdk,
        "POLYMARKET_PRIVATE_KEY": _WALLET,
        "POLYMARKET_FUNDER_ADDRESS": os.getenv("STAGING_FUNDER_ADDRESS"),
        "POLYMARKET_SIGNATURE_TYPE": int(os.getenv("STAGING_SIGNATURE_TYPE", "2")),
        "POLYMARKET_API_KEY": os.getenv("STAGING_POLYMARKET_API_KEY"),
        "POLYMARKET_API_SECRET": os.getenv("STAGING_POLYMARKET_API_SECRET"),
        "POLYMARKET_API_PASSPHRASE": os.getenv("STAGING_POLYMARKET_API_PASSPHRASE"),
    })


async def _ensure_staging_creds(s: Any) -> None:
    """Resolve L2 API creds for the staging wallet into the same cache the CLOB
    client reads (env creds > module-level ``_derived``), so the persistent
    ``broker`` fixture client AND every ``_factory``-built client share them.

    Mirrors production ``ensure_clob_credentials`` (GET /auth/derive-api-key),
    but a FRESH throwaway wallet has nothing to derive yet — the CLOB returns
    ``400 "Could not derive api key!"``. In that one case we fall back to
    POST /auth/api-key (create) ONCE to self-provision the key, then populate
    the same ``_derived`` cache. Any OTHER auth failure (e.g. a signature-type
    mismatch) is re-raised untouched so it surfaces instead of being masked.
    """
    if _clob_mod._derived:                  # already resolved earlier this run —
        return                              # reuse the cache, no redundant auth call
    try:
        await ensure_clob_credentials(s)   # no-op if API creds already in env
    except ClobAuthError as exc:
        if "could not derive" not in str(exc).lower():
            raise
        tmp = ClobAdapter(
            api_key="", api_secret="", passphrase="",
            private_key=s.POLYMARKET_PRIVATE_KEY,
            funder_address=s.POLYMARKET_FUNDER_ADDRESS,
            signature_type=s.POLYMARKET_SIGNATURE_TYPE,
            circuit_breaker=get_clob_breaker(s),
            rate_limiter=get_clob_rate_limiter(s),
        )
        try:
            creds = await tmp.create_api_credentials()
        finally:
            await tmp.aclose()
        # Populate the SAME cache get_clob_client reads, so _factory clients
        # (which build from bare settings) pick the freshly-created creds up.
        _clob_mod._derived = {
            "api_key": creds.get("apiKey") or creds.get("api_key", ""),
            "api_secret": creds.get("secret") or creds.get("api_secret", ""),
            "passphrase": creds.get("passphrase", ""),
        }


async def _new_client():
    s = _staging_settings()
    await _ensure_staging_creds(s)   # derive; create once on a fresh wallet
    return get_clob_client(s), s


def _factory(_s: Any = None):
    """A FRESH throwaway client per call. The reconcile/drift functions ``aclose``
    whatever the factory returns, so this must NOT be the persistent ``broker``
    fixture client (creds are cached after the fixture's first derive)."""
    return get_clob_client(_staging_settings())


async def _place_resting_buy(client, *, price: float = _REST_PRICE,
                             shares: float = _SHARES) -> str:
    """Place a tiny GTC BUY far below market so it RESTS (never fills). Returns id."""
    resp = await client.post_order(
        token_id=_TOKEN, side="buy", price=price, size=shares,
        order_type="GTC", tick_size=_TICK, neg_risk=_NEG_RISK,
    )
    import json as _json
    import sys as _sys
    print("DIAG post_order_resp=", _json.dumps(resp, default=str)[:1500],
          file=_sys.stderr, flush=True)
    bid = _broker_id(resp) if isinstance(resp, dict) else ""
    assert bid, f"staging post_order returned no order id: {resp!r}"
    return bid


@pytest_asyncio.fixture
async def broker():
    """Yield a real staging client; cancel ALL of its resting orders on teardown
    so each case is fully independent (no shared state between cases)."""
    await _ensure_market_resolved()   # resolve a live open market (or honour env)
    client, _s = await _new_client()
    try:
        yield client
    finally:
        try:
            await client.cancel_all_orders()
        except Exception:  # noqa: BLE001 — best-effort cleanup, never mask result
            pass
        try:
            await client.aclose()
        except Exception:  # noqa: BLE001
            pass


# --- recording fake pool (DB side is NEVER real — only the broker is) ---------
class _Tx:
    async def __aenter__(self) -> "_Tx":
        return self

    async def __aexit__(self, *_a: Any) -> bool:
        return False


class _Conn:
    def __init__(self, *, scan_rows=None, tracked_rows=None, market_row=None,
                 closing_rows=None, drift_rows=None, finalize_id=None) -> None:
        self.scan_rows = scan_rows or []
        self.tracked_rows = tracked_rows or []
        self.market_row = market_row
        self.closing_rows = closing_rows or []
        self.drift_rows = drift_rows or []
        self.finalize_id = finalize_id
        self.executed: list[tuple[str, tuple]] = []

    async def fetch(self, q: str, *_a: Any) -> list[dict]:
        if "o.status = 'unknown'" in q:
            return self.scan_rows
        if "WHERE mode='live' AND status = ANY" in q:
            return self.drift_rows
        if "SELECT polymarket_order_id FROM orders" in q:
            return self.tracked_rows
        if "FROM positions WHERE mode='live' AND status='closing'" in q:
            return self.closing_rows
        return []

    async def fetchrow(self, q: str, *_a: Any) -> Optional[dict]:
        return self.market_row if "FROM markets" in q else None

    async def fetchval(self, q: str, *_a: Any) -> Any:
        if "status='closed'" in q and "RETURNING id" in q:
            return self.finalize_id
        return None

    async def execute(self, q: str, *a: Any) -> str:
        self.executed.append((q, a))
        return "OK"

    def transaction(self) -> _Tx:
        return _Tx()


class _Acquire:
    def __init__(self, conn: _Conn) -> None:
        self._conn = conn

    async def __aenter__(self) -> _Conn:
        return self._conn

    async def __aexit__(self, *_a: Any) -> bool:
        return False


class _Pool:
    def __init__(self, conn: _Conn) -> None:
        self._conn = conn

    def acquire(self) -> _Acquire:
        return _Acquire(self._conn)


@pytest.fixture
def pages(monkeypatch):
    """Capture every operator page across the reconcile / kill / drift modules so
    a case can assert the EXACT alert the runbook tells the operator to expect."""
    sent: list[str] = []

    async def _notify(text, *_a, **_k):
        sent.append(text)

    # Every caller resolves notify_operator on the package's notifications module
    # at call time (``from ... import notifications`` / lazy ``from ...notifications
    # import notify_operator``), so patching the one canonical attribute covers the
    # reconcile, drift, kill-switch and router paths alike.
    monkeypatch.setattr(
        "projects.polymarket.crusaderbot.notifications.notify_operator", _notify)
    return sent


def _market_row() -> dict:
    return {"yes_token_id": _TOKEN, "no_token_id": _NO_TOKEN or "NO_TOKEN"}


def _unknown_row(**over: Any) -> dict:
    base = {"id": uuid4(), "user_id": uuid4(), "market_id": _MARKET, "side": "yes",
            "size_usdc": round(_REST_PRICE * _SHARES, 4), "price": _REST_PRICE,
            "polymarket_order_id": "", "status": "unknown",
            "strategy_type": "late_entry_v3"}
    base.update(over)
    return base


def _closing_row(**over: Any) -> dict:
    base = {"id": uuid4(), "user_id": uuid4(), "market_id": _MARKET, "side": "yes",
            "size_usdc": round(_REST_PRICE * _SHARES, 4), "entry_price": _REST_PRICE,
            "current_price": _REST_PRICE, "close_order_id": "", "closing_at": None}
    base.update(over)
    return base


def _settings_live(**over: Any) -> SimpleNamespace:
    base = dict(USE_REAL_CLOB=True, LIVE_RECONCILE_ENABLED=True,
                LIVE_RECONCILE_STALE_SEC=0, LIVE_CLOSING_STALE_SEC=0,
                ORDER_DRIFT_DETECT_ENABLED=True)
    base.update(over)
    return SimpleNamespace(**base)


async def _poll_open_order(broker, bid: str, *, present: bool,
                           tries: int = 10, delay: float = 1.5) -> bool:
    """Poll the broker's open orders until `bid` matches `present` (resting/gone).

    Polymarket's /data/orders read is eventually-consistent AFTER a POST or a
    cancel, so a single immediate read is racy: the order may not appear (or not
    yet disappear) on the first query. Polls the market-scoped list first, then
    the unscoped list as a fallback — covering both read-after-write lag and any
    market-filter quirk. Returns the last observed 'is present'."""
    import asyncio
    seen = not present
    for _ in range(tries):
        try:
            ids = {_broker_id(o) for o in await broker.get_open_orders(_MARKET)}
            if bid not in ids:                  # fall back to the unscoped list
                ids |= {_broker_id(o) for o in await broker.get_open_orders()}
        except Exception:  # noqa: BLE001 — transient read error: retry next tick
            await asyncio.sleep(delay)
            continue
        seen = bid in ids
        if seen == present:
            return seen
        await asyncio.sleep(delay)
    return seen


# ============================================================================
# CASE 3 — kill switch broker cancel-all (the headline real-broker proof)
# ============================================================================
async def test_case3_kill_switch_cancels_resting_gtc(broker, monkeypatch, pages):
    """A REAL resting GTC must be GONE from the broker after the kill switch —
    proving _broker_cancel_all_orders pulls live exchange orders, not just DB rows.
    """
    _need_market()
    bid = await _place_resting_buy(broker)

    # --- root-cause diagnostics (one dispatch must explain a missing readback) ---
    import json as _json
    import sys as _sys

    def _diag(label: str, val: Any) -> None:
        print(f"DIAG {label}=", _json.dumps(val, default=str)[:2500],
              file=_sys.stderr, flush=True)

    _diag("market_id", _MARKET)
    _diag("token_id", _TOKEN)
    _diag("signature_type", getattr(broker, "signature_type", "?"))
    _diag("signer_address", getattr(broker, "address", "?"))
    _diag("funder_address", getattr(broker, "funder", "?"))
    _diag("placed_bid", bid)
    try:
        _diag("open_orders_scoped_raw", await broker.get_open_orders(_MARKET))
    except Exception as _e:  # noqa: BLE001
        _diag("open_orders_scoped_err", f"{type(_e).__name__}: {_e}")
    try:
        _diag("open_orders_unscoped_raw", await broker.get_open_orders())
    except Exception as _e:  # noqa: BLE001
        _diag("open_orders_unscoped_err", f"{type(_e).__name__}: {_e}")

    assert await _poll_open_order(broker, bid, present=True), \
        "precondition: the staging GTC should be resting on the book"

    # Drive the REAL kill-switch broker-cancel. It builds + acloses its OWN staging
    # client (via the real get_clob_client + staging settings), so the persistent
    # ``broker`` fixture client stays open to verify the order is gone afterwards.
    monkeypatch.setattr(kse, "get_settings", lambda: _staging_settings())
    res = await kse._broker_cancel_all_orders()
    assert res["attempted"] and res["cancelled"], res

    assert not await _poll_open_order(broker, bid, present=False), \
        f"GTC {bid} STILL LIVE after kill switch"


# ============================================================================
# CASE 2 — unknown-order reconcile against real broker truth
# ============================================================================
@pytest.mark.parametrize("variant", ["adopt", "mismatch", "halt"])
async def test_case2_unknown_order_reconcile(broker, monkeypatch, pages, variant):
    """reconcile_live_orders resolves a directional 'unknown' against the REAL
    open-order book: a uniquely-matched resting order is ADOPTED, a non-matching
    lone order PAGES, two untracked orders HALT + page."""
    _need_market()
    conn = _Conn(scan_rows=[_unknown_row()], tracked_rows=[], market_row=_market_row())
    pool = _Pool(conn)
    monkeypatch.setattr(lr, "get_pool", lambda: pool)
    killed: list[Any] = []
    monkeypatch.setattr(
        "projects.polymarket.crusaderbot.domain.ops.kill_switch.set_active",
        lambda **kw: killed.append(kw) or _noop())

    if variant == "adopt":
        await _place_resting_buy(broker)   # price+size match the unknown row
    elif variant == "mismatch":
        await _place_resting_buy(broker, price=max(_REST_PRICE * 3, 0.30), shares=_SHARES)
    else:  # halt — two distinct untracked resting orders on the same token
        await _place_resting_buy(broker)
        await _place_resting_buy(broker, price=round(_REST_PRICE + float(_TICK), 4))

    res = await lr.reconcile_live_orders(
        pool=pool, clob_factory=_factory, settings=_settings_live())

    if variant == "adopt":
        assert res["adopted"] == 1, res
        assert any("status='pending'" in q for q, _a in conn.executed)
    elif variant == "mismatch":
        assert res["paged"] == 1 and res["adopted"] == 0, res
        assert any("size_price_mismatch" in str(a) for _q, a in conn.executed)
    else:
        assert res["halted"] == 1, res
        assert killed, "ambiguous untracked exposure must engage the kill switch"
        assert any("UNTRACKED EXPOSURE" in p for p in pages)


async def _noop(*_a: Any, **_k: Any) -> None:
    """Awaitable no-op usable directly as an async mock (ignores any call args)."""
    return None


# ============================================================================
# CASE 1 — crash-mid-close reconcile against real broker truth
# ============================================================================
async def test_case1_closing_rollback_on_cancelled_sell(broker, monkeypatch, pages):
    """A stranded 'closing' whose close SELL was definitively NOT executed
    (placed then cancelled → terminal, zero fills) must ROLL BACK to 'open'."""
    _need_market()
    close_id = await _place_resting_buy(broker)        # stand-in resting close order
    await broker.cancel_order(close_id)                 # → terminal, zero fills

    conn = _Conn(closing_rows=[_closing_row(close_order_id=close_id)])
    pool = _Pool(conn)
    monkeypatch.setattr(lr, "get_pool", lambda: pool)
    res = await lr.reconcile_closing_positions(
        pool=pool, clob_factory=_factory, settings=_settings_live())

    assert res["rolled_back"] == 1, res
    assert any("status='open'" in q for q, _a in conn.executed)


async def test_case1_closing_pages_when_no_close_order_id(broker, monkeypatch, pages):
    """A 'closing' row with no persisted close_order_id is unverifiable → PAGE,
    never assume a fill (no real order placed; pure routing on real settings)."""
    _need_market()
    conn = _Conn(closing_rows=[_closing_row(close_order_id=None)])
    pool = _Pool(conn)
    monkeypatch.setattr(lr, "get_pool", lambda: pool)
    res = await lr.reconcile_closing_positions(
        pool=pool, clob_factory=_factory, settings=_settings_live())
    assert res["paged_no_id"] == 1 and pages


@pytest.mark.skipif(not _ALLOW_FILLS,
                    reason="finalize-once burns real USDC — set STAGING_ALLOW_FILLS=1")
async def test_case1_closing_finalize_once_on_filled_sell(broker, monkeypatch, pages):
    """Fill-gated: the operator forces a REAL marketable fill of the close order;
    reconcile_closing_positions must finalize the position exactly ONCE and credit
    proceeds. Driven by the operator per the runbook — see STAGING_FILLED_CLOSE_ID."""
    _need_market()
    filled_close_id = os.getenv("STAGING_FILLED_CLOSE_ID")
    if not filled_close_id:
        pytest.skip("set STAGING_FILLED_CLOSE_ID to a terminally-FILLED close order")

    row = _closing_row(close_order_id=filled_close_id)
    conn = _Conn(closing_rows=[row], finalize_id=row["id"])
    pool = _Pool(conn)
    monkeypatch.setattr(lr, "get_pool", lambda: pool)
    credited: list[Any] = []
    monkeypatch.setattr(
        "projects.polymarket.crusaderbot.wallet.ledger.credit_in_conn",
        lambda *a, **k: credited.append(a) or _noop())

    res = await lr.reconcile_closing_positions(
        pool=pool, clob_factory=_factory, settings=_settings_live())
    assert res["closed"] == 1 and credited, res
    # finalize-ONCE: in the real DB the finalized row is now 'closed' and leaves
    # the 'closing' scan set, so a second sweep finds nothing to re-finalize. (The
    # static mock conn would otherwise re-serve the same row, and
    # _reconcile_one_closing returns "closed" unconditionally on a FILLED broker
    # state — so we must model the row leaving the set, not rely on finalize_id.)
    conn.finalize_id = None
    conn.closing_rows = []
    res2 = await lr.reconcile_closing_positions(
        pool=pool, clob_factory=_factory, settings=_settings_live())
    assert res2["closed"] == 0, "second sweep must not re-finalize a closed position"


# ============================================================================
# CASE 4 — broker<->DB drift detector surfaces a real orphan, mutates nothing
# ============================================================================
async def test_case4_drift_surfaces_broker_only_and_db_only(broker, monkeypatch, pages):
    """A REAL resting order untracked in the DB must surface as broker-only; a DB
    id absent from the broker as db-only; the detector mutates NO order rows."""
    _need_market()
    bid = await _place_resting_buy(broker)
    phantom = f"db-only-{uuid4().hex[:12]}"
    conn = _Conn(drift_rows=[{"polymarket_order_id": phantom}])  # NOT bid → broker-only
    pool = _Pool(conn)
    monkeypatch.setattr(dd, "get_pool", lambda: pool)

    res = await dd.detect_order_drift(
        pool=pool, clob_factory=_factory, settings=_settings_live())
    assert res["checked"] and res["broker_only"] >= 1 and res["db_only"] >= 1, res
    assert any(bid in p for p in pages), "real orphan id must appear in the page"
    # ALERT-ONLY: drift detection must never UPDATE/INSERT an order row.
    assert not any(q.strip().upper().startswith(("UPDATE", "INSERT", "DELETE"))
                   for q, _a in conn.executed), conn.executed


# ============================================================================
# CASE 5 — infra-degraded live path falls back to PAPER + alerts
# ============================================================================
async def test_case5_infra_degraded_falls_back_to_paper_and_alerts(monkeypatch, pages):
    """When a CLOB dependency fails pre-submit, router.execute must route the trade
    to PAPER and emit the LIVE INFRA DEGRADED operator alert (no wallet needed —
    kept in the staging suite as the degraded-path contract check)."""
    from decimal import Decimal

    from projects.polymarket.crusaderbot.domain.execution import router
    from projects.polymarket.crusaderbot.domain.execution.live import LivePreSubmitError

    async def _boom(**_k):
        raise LivePreSubmitError("CLOB market metadata unavailable")

    paper_calls: list[dict] = []

    async def _paper(**kw):
        paper_calls.append(kw)
        return {"mode": "paper", "status": "filled"}

    monkeypatch.setattr(router.live_engine, "assert_live_guards", lambda *a, **k: None)
    monkeypatch.setattr(router.live_engine, "execute", _boom)
    monkeypatch.setattr(router.paper_engine, "execute", _paper)
    monkeypatch.setattr(router.audit, "write", lambda **k: _noop())

    out = await router.execute(
        chosen_mode="live", user_id=uuid4(), telegram_user_id=1, role="admin",
        market_id=_MARKET or "m1", market_question="q", yes_token_id="y",
        no_token_id="n", side="yes", size_usdc=Decimal("1"), price=0.5,
        idempotency_key="k", strategy_type="late_entry_v3", tp_pct=None, sl_pct=None,
        trading_mode="live")

    assert out.get("mode") == "paper" and paper_calls, out
    assert any("LIVE INFRA DEGRADED" in p for p in pages), pages
