"""PlaybookStrategy — BaseStrategy adapter for the PLAYBOOK sports router.

PLAYBOOK is the sports equivalent of SMART STRIKE: one ``BaseStrategy`` that
internally owns the Market Quality Filter, the signal layer, and the
precedence-claim router (``domain/playbook/``), exactly as ``LateEntryV3Strategy``
owns the Close/Safe/Flip rules behind ``candle_auto``. The router selects one
module per market and this adapter emits a standard ``SignalCandidate`` for the
existing risk gate + execution router to consume.

Phase-1 claim level = FOUNDATION (paper-only). The decision path
(quality → signals → router → candidate) is fully wired and unit-tested via
``evaluate_snapshot``. ``scan`` returns ``[]`` until the sports-market data
source is wired into the signal-scan loop (Phase-2, mirrors the
``weather_monitor`` → ``weather`` dispatch). No new risk/execution authority is
introduced — all caps remain enforced by ``domain/risk/gate.py``.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from ...playbook.correlation import cluster_key
from ...playbook.market_quality import evaluate_market_quality
from ...playbook.modules import MarketSnapshot
from ...playbook.router import PlaybookRouter
from ...playbook.signals import compute_signal_bundle
from ..base import BaseStrategy
from ..types import ExitDecision, MarketFilters, SignalCandidate, UserContext

log = logging.getLogger(__name__)

_PLAYBOOK_STRATEGY_NAME = "playbook"

# Default closing-proximity window used when assembling the signal bundle TTL
# feed. Kept in sync with ClosingEdgeModule's entry window.
_CLOSE_WINDOW_SEC: float = 1_800.0

# Sports market categories this strategy is eligible for. Used by the Phase-2
# scan-loop fetch to narrow the universe (the crypto-candle path uses
# is_short_crypto_market; PLAYBOOK uses sports categories instead).
SPORTS_CATEGORIES: tuple[str, ...] = (
    "sports",
    "nfl",
    "nba",
    "mlb",
    "nhl",
    "soccer",
    "ufc",
    "mma",
    "tennis",
)

# Only assemble snapshots for markets whose event is within this pre-event
# window. Closing Edge (the only live module) acts inside 30 min, so a 2h cap
# bounds the per-scan orderbook fetches while still covering the entry window.
_SNAPSHOT_TTL_CAP_SEC: float = 7_200.0
# Hard cap on orderbook fetches per scan (2 books per market).
_MAX_SPORTS_MARKETS_PER_SCAN: int = 40
# Per-trade sizing fraction applied to deployable equity before the risk gate
# re-sizes via fractional Kelly + caps. Conservative base; gate is authoritative.
_SIZE_EQUITY_FRACTION: float = 0.04
_DEFAULT_SIZE_CEILING_USDC: float = 25.0


def _parse_iso(ts: object) -> datetime | None:
    """Parse an ISO-8601 timestamp (tolerating a trailing Z); None on failure."""
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return d if d.tzinfo is not None else d.replace(tzinfo=timezone.utc)


def _is_sports_category(category: object) -> bool:
    """True if the event's category tags name any tracked sport."""
    c = str(category or "").lower()
    return any(tok in c for tok in SPORTS_CATEGORIES)


def _extract_token_ids(market: dict) -> list[str]:
    """Return [yes_token_id, no_token_id] from a Gamma market dict, or []."""
    raw = market.get("clobTokenIds") or market.get("clob_token_ids")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            raw = None
    if isinstance(raw, list) and len(raw) >= 2 and raw[0] and raw[1]:
        return [str(raw[0]), str(raw[1])]
    toks = market.get("tokens")
    if (
        isinstance(toks, list)
        and len(toks) >= 2
        and isinstance(toks[0], dict)
        and isinstance(toks[1], dict)
    ):
        a, b = toks[0].get("token_id"), toks[1].get("token_id")
        if a and b:
            return [str(a), str(b)]
    return []


def _best_ask(book: dict) -> float | None:
    """Lowest ask price in a CLOB book, or None when there is no ask."""
    if not isinstance(book, dict):
        return None
    asks = book.get("asks") or []
    prices = []
    for lvl in asks:
        try:
            prices.append(float(lvl["price"]))
        except (KeyError, TypeError, ValueError):
            continue
    return min(prices) if prices else None


def _best_bid(book: dict) -> float | None:
    """Highest bid price in a CLOB book, or None when there is no bid."""
    if not isinstance(book, dict):
        return None
    bids = book.get("bids") or []
    prices = []
    for lvl in bids:
        try:
            prices.append(float(lvl["price"]))
        except (KeyError, TypeError, ValueError):
            continue
    return max(prices) if prices else None


def _fair_price(yes_bid: float | None, yes_ask: float | None, market: dict) -> float:
    """Estimate P(YES) as the consensus fair value.

    Prefers the Gamma consensus (AMM/last) price — it is INDEPENDENT of the live
    CLOB ask, so a CLOB resting order priced below it surfaces as a positive
    Closing-Edge edge (stale book vs consensus). Using the book's own mid would
    make ``fair - ask`` structurally ≤ 0, so the book mid is only a last resort
    when Gamma carries no usable price (edge ≈ 0 → no claim, which is correct).
    """
    op = market.get("outcomePrices") or market.get("yes_price")
    if isinstance(op, str):
        try:
            op = json.loads(op)
        except (ValueError, TypeError):
            op = None
    try:
        v = float(op[0]) if isinstance(op, (list, tuple)) and op else (
            float(op) if op is not None else None
        )
        if v is not None and 0.0 < v < 1.0:
            return v
    except (TypeError, ValueError):
        pass
    if yes_bid is not None and yes_ask is not None and 0.0 < yes_bid <= yes_ask < 1.0:
        return (yes_bid + yes_ask) / 2.0
    return 0.5


def _suggested_size_usdc(user_context: UserContext) -> float:
    """Bounded base size before the risk gate's Kelly + position caps apply."""
    base = user_context.equity_usdc or user_context.available_balance_usdc
    size = max(0.0, base * user_context.capital_allocation_pct * _SIZE_EQUITY_FRACTION)
    ceiling = (
        user_context.max_per_trade_usdc
        if user_context.max_per_trade_usdc is not None
        else _DEFAULT_SIZE_CEILING_USDC
    )
    return round(min(size, ceiling), 2) if ceiling else round(size, 2)


class PlaybookStrategy(BaseStrategy):
    """Autonomous sports-market orchestration router.

    Wraps ``domain/playbook`` into the CrusaderBot domain strategy plane.
    """

    name: str = _PLAYBOOK_STRATEGY_NAME
    version: str = "1.0.0"
    risk_profile_compatibility: list[str] = [
        "conservative",
        "balanced",
        "aggressive",
        "custom",
    ]

    def __init__(self, router: PlaybookRouter | None = None) -> None:
        self._router = router if router is not None else PlaybookRouter()

    def default_tp_sl(self) -> tuple[float, float]:
        """Balanced-profile defaults; per-module TP/SL overrides via metadata."""
        return (0.25, 0.12)

    async def scan(
        self,
        market_filters: MarketFilters,
        user_context: UserContext,
    ) -> list[SignalCandidate]:
        """Emit sports SignalCandidates for the user.

        Fetches sports market snapshots (``_fetch_sports_snapshots``), runs each
        through quality → signals → router (``evaluate_snapshot``), and returns
        the emitted candidates highest-confidence first. Never raises — a fetch
        failure yields an empty list. The scan loop gates invocation behind the
        ``playbook`` preset + the ``PLAYBOOK_STRATEGY_ENABLED`` operator flag.
        """
        snapshots = await self._fetch_sports_snapshots(market_filters, user_context)
        candidates: list[SignalCandidate] = []
        for snapshot in snapshots:
            candidate = self.evaluate_snapshot(snapshot, user_context)
            if candidate is not None:
                candidates.append(candidate)
        # Highest confidence first, matching the candle path's ordering.
        candidates.sort(key=lambda c: c.confidence, reverse=True)
        return candidates

    async def _fetch_sports_snapshots(
        self,
        market_filters: MarketFilters,
        user_context: UserContext,
    ) -> list[MarketSnapshot]:
        """Fetch sports markets + orderbooks and assemble MarketSnapshots.

        Mirrors the weather global-markets pattern: one cached Gamma fetch
        (``get_events_with_markets``), pre-filtered to sports categories within
        the pre-event window so only a bounded set needs orderbook reads, then a
        cached CLOB ``get_book`` per leg. Every external call is fail-soft — a
        fetch error logs and skips, never raises into the scan loop.
        """
        from ....integrations import polymarket as pm

        try:
            markets = await pm.get_events_with_markets(limit=200)
        except Exception as exc:  # noqa: BLE001 — fail-soft, never break scan loop
            log.warning("playbook: sports market fetch failed: %s", exc)
            return []

        if not markets or not isinstance(markets, list):
            return []

        now = datetime.now(timezone.utc)
        blacklist = set(market_filters.blacklisted_market_ids or [])
        # Pre-filter to sports markets inside the close window, nearest-first, so
        # the orderbook-fetch budget covers the markets that can actually route.
        prelim: list[tuple[dict, str, str, float]] = []
        for m in markets:
            if not isinstance(m, dict):
                continue
            category = str(m.get("category") or "")
            if not _is_sports_category(category):
                continue
            market_id = str(m.get("id") or m.get("conditionId") or "")
            if not market_id or market_id in blacklist:
                continue
            start = _parse_iso(
                m.get("gameStartTime")
                or m.get("game_start_time")
                or m.get("endDate")
                or m.get("end_date_iso")
            )
            if start is None:
                continue
            ttl = (start - now).total_seconds()
            if not (0.0 < ttl <= _SNAPSHOT_TTL_CAP_SEC):
                continue
            prelim.append((m, market_id, category, ttl))

        prelim.sort(key=lambda t: t[3])
        prelim = prelim[:_MAX_SPORTS_MARKETS_PER_SCAN]

        size = _suggested_size_usdc(user_context)
        snapshots: list[MarketSnapshot] = []
        for m, market_id, category, ttl in prelim:
            token_ids = _extract_token_ids(m)
            if len(token_ids) < 2:
                continue
            try:
                yes_book = await pm.get_book(token_ids[0])
                no_book = await pm.get_book(token_ids[1])
            except Exception as exc:  # noqa: BLE001 — fail-soft per market
                log.warning("playbook: book fetch failed for %s: %s", market_id, exc)
                continue

            yes_bid = _best_bid(yes_book)
            yes_ask = _best_ask(yes_book)
            no_ask = _best_ask(no_book)
            if yes_ask is None or no_ask is None:
                continue

            liquidity = float(m.get("liquidity_usdc") or m.get("liquidity") or 0.0)
            condition_id = str(m.get("conditionId") or m.get("condition_id") or market_id)
            snapshots.append(
                MarketSnapshot(
                    market_id=market_id,
                    condition_id=condition_id,
                    sport=category,
                    fair_price=_fair_price(yes_bid, yes_ask, m),
                    yes_ask=yes_ask,
                    no_ask=no_ask,
                    seconds_to_event=ttl,
                    liquidity_usdc=liquidity,
                    suggested_size_usdc=size,
                    cluster_key=cluster_key(
                        sport=category,
                        event_id=str(m.get("conditionId") or m.get("slug") or market_id),
                    ),
                )
            )
        return snapshots

    def evaluate_snapshot(
        self,
        snapshot: MarketSnapshot,
        user_context: UserContext,
    ) -> SignalCandidate | None:
        """Run quality → signals → router for one snapshot; emit a candidate.

        Returns ``None`` when the market fails quality or no module claims it.
        This is the unit-testable core of the strategy.
        """
        # Binary-market YES book: the YES bid is implied by the NO ask
        # (buying NO at no_ask ⇒ willing to sell YES at 1 - no_ask), and the
        # YES ask is yes_ask. The spread is therefore yes_ask + no_ask - 1.
        yes_bid = 1.0 - snapshot.no_ask
        quality = evaluate_market_quality(
            liquidity_usdc=snapshot.liquidity_usdc,
            best_bid=yes_bid,
            best_ask=snapshot.yes_ask,
            top_depth_usdc=snapshot.liquidity_usdc,
            resolution_clear=True,
            event_integrity_ok=True,
        )
        if not quality.accepted:
            log.debug("playbook: market %s rejected by quality: %s",
                      snapshot.market_id, quality.reason)
            return None

        mid = snapshot.fair_price
        bundle = compute_signal_bundle(
            market_id=snapshot.market_id,
            mid_now=mid,
            mid_prev=mid,
            noise_sigma=0.05,
            liquidity_usdc=snapshot.liquidity_usdc,
            spread=max(0.0, (snapshot.yes_ask + snapshot.no_ask) - 1.0),
            seconds_to_event=snapshot.seconds_to_event,
            close_window_sec=_CLOSE_WINDOW_SEC,
            buy_flow_usdc=0.0,
            sell_flow_usdc=0.0,
            sharp_signed_usdc=0.0,
            total_flow_usdc=0.0,
        )

        result = self._router.route(snapshot, bundle)
        if not result.routed or result.decision is None:
            return None

        decision = result.decision
        key = snapshot.cluster_key or cluster_key(sport=snapshot.sport)
        metadata = {
            **decision.metadata,
            "selected_module": result.module,
            "cluster_key": key,
            "tp_pct": decision.tp_pct,
            "sl_pct": decision.sl_pct,
            "engine": "playbook",
        }
        return SignalCandidate(
            market_id=snapshot.market_id,
            condition_id=snapshot.condition_id,
            side=decision.side,
            confidence=decision.confidence,
            suggested_size_usdc=decision.suggested_size_usdc,
            strategy_name=self.name,
            signal_ts=datetime.now(timezone.utc),
            metadata=metadata,
            reasoning=decision.reasoning,
        )

    async def evaluate_exit(self, position: dict) -> ExitDecision:
        """Per-position exit: module force-exit window, then price collapse.

        Mirrors the LateEntryV3 exit contract — the exit watcher injects
        ``seconds_to_close`` (seconds to event) and optionally
        ``force_exit_at_rem_sec``; when the watcher omits the threshold we fall
        back to the module's ``force_exit_at_event_sec`` stamped in
        ``strategy_metadata`` at entry. Missing data → hold (TP/SL + expiry
        paths still protect the position).
        """
        meta = position.get("strategy_metadata") or {}
        force_at = position.get("force_exit_at_rem_sec")
        if force_at is None:
            force_at = meta.get("force_exit_at_event_sec")
        secs_left = position.get("seconds_to_close")

        if force_at is not None and secs_left is not None:
            try:
                _force = float(force_at)
                _left = float(secs_left)
            except (TypeError, ValueError):
                _force = _left = None  # type: ignore[assignment]
            if _force is not None and _force > 0.0 and _left is not None and _left <= _force:
                return ExitDecision(
                    should_exit=True,
                    reason="strategy_exit",
                    metadata={
                        "force_exit_at_event_sec": _force,
                        "seconds_to_close": _left,
                        "trigger": "closing_edge_force_exit",
                    },
                )

        cur = position.get("current_price")
        try:
            price = float(cur) if cur is not None else None
        except (TypeError, ValueError):
            price = None
        if price is not None and price <= 0.05:
            return ExitDecision(
                should_exit=True,
                reason="strategy_exit",
                metadata={"trigger": "price_collapse", "current_price": price},
            )

        return ExitDecision(should_exit=False, reason="hold")


__all__ = ["PlaybookStrategy", "SPORTS_CATEGORIES"]
