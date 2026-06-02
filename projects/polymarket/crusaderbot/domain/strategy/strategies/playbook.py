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

        Phase-1 FOUNDATION: there is no sports-market data source wired into the
        scan loop yet, so this returns an empty list (never raises). The full
        decision path is implemented and exercised via ``evaluate_snapshot``;
        Phase-2 wires ``_fetch_sports_snapshots`` to the live market feed
        following the ``weather`` dispatch precedent.
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
        """Return sports MarketSnapshots for routing.

        Phase-1 returns ``[]`` — the sports-market fetch + orderbook snapshot
        assembly is a Phase-2 integration (mirrors the weather global-markets
        fetch). Isolated here so wiring it later does not touch the router.
        """
        log.debug("playbook._fetch_sports_snapshots: no sports source wired (phase-1)")
        return []

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
