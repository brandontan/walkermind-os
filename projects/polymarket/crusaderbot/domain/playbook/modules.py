"""PLAYBOOK strategy modules.

Each module is a self-contained sports edge with a uniform contract: given a
``MarketSnapshot`` and the computed ``SignalBundle``, decide whether to *claim*
the market and, if so, with what side / size / confidence / TP-SL. The router
walks modules in precedence order and the first to claim wins (see
``router.py``).

Phase-1 ships ``ClosingEdgeModule`` fully implemented (Polymarket-native, the
MVP). ``SharpMoneyModule`` carries a native formula but its on-chain source is
promoted in V2. ``PublicFadeModule`` and ``InjuryAlphaModule`` are declared
stubs (feed-dependent) — present in the matrix, returning no claim until their
``SportsFeed`` adapters land. Adding a module is wiring its gate, not
re-architecting the router.

Pure decision logic — no DB, no execution, no risk evaluation here.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from . import signals as S
from .signals import SignalBundle

# --- Closing Edge tunables (PLAYBOOK-local; calibratable by the V2 backtester) ---
CLOSING_EDGE_WINDOW_SEC: float = 1_800.0  # act only inside the final 30 min pre-event
CLOSING_EDGE_MIN_EDGE: float = 0.03  # min (fair - ask) edge to claim a side
CLOSING_EDGE_EDGE_SCALE: float = 0.10  # edge that maps to full edge-confidence
CLOSING_EDGE_FORCE_EXIT_SEC: float = 60.0  # exit window before event start
CLOSING_EDGE_TP_PCT: float = 0.25
CLOSING_EDGE_SL_PCT: float = 0.12

# --- Sharp Money tunables (PLAYBOOK-local; calibratable by the V2 backtester) ---
SHARP_MONEY_MIN_TTL_SEC: float = 86_400.0  # only far from event (TTL > 24h)
SHARP_MONEY_MIN_CONFIDENCE: float = 0.20  # min sharp-imbalance confidence to claim
SHARP_MONEY_MIN_FLOW_USDC: float = 500.0  # ignore thin sharp flow (noise floor)
SHARP_MONEY_TP_PCT: float = 0.30
SHARP_MONEY_SL_PCT: float = 0.15

# --- Injury Alpha tunables (Phase-2d; feed-dependent — calibratable by backtest) ---
INJURY_MIN_TTL_SEC: float = 3_600.0  # blueprint: only act with TTL > 1h to repricing
INJURY_MIN_CONFIDENCE: float = 0.20  # min injury-reading confidence to claim
INJURY_MAX_REPRICED_FRACTION: float = 0.50  # book already absorbed ≥50% → no edge left
INJURY_TP_PCT: float = 0.30
INJURY_SL_PCT: float = 0.15

# --- Public Fade tunables (Phase-2e; feed-dependent — calibratable by backtest) ---
PUBLIC_FADE_MIN_TTL_SEC: float = 1_800.0  # stay outside Closing Edge's window (clean split)
PUBLIC_FADE_MIN_PCT: float = 0.65  # public-imbalance threshold θ (share of public tickets)
PUBLIC_FADE_MIN_OVERREACTION: float = 0.10  # public_pct − market-implied prob on that side
PUBLIC_FADE_OVERREACTION_SCALE: float = 0.30  # overreaction mapping to full confidence
PUBLIC_FADE_MIN_CONFIDENCE: float = 0.20
PUBLIC_FADE_TP_PCT: float = 0.30
PUBLIC_FADE_SL_PCT: float = 0.15


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


@dataclass(frozen=True)
class MarketSnapshot:
    """Immutable per-scan view of a sports market handed to every module.

    ``fair_price`` is the estimated P(YES) (Phase-1: derived from the book mid;
    V2 can substitute a model/consensus probability). ``yes_ask`` / ``no_ask``
    are the costs to buy each side. ``cluster_key`` comes from the correlation
    engine.
    """

    market_id: str
    condition_id: str
    sport: str
    fair_price: float  # estimated P(YES) in (0, 1)
    yes_ask: float
    no_ask: float
    seconds_to_event: float
    liquidity_usdc: float
    suggested_size_usdc: float
    cluster_key: str = "unclustered"
    # Native sharp-money flow (Phase-2b) — top-tier wallet signed/total USDC over
    # the lookback, sourced DB-backed in the async snapshot assembly. Default 0.0
    # keeps evaluate_snapshot pure + Phase-1 callers/tests unchanged.
    sharp_signed_usdc: float = 0.0
    sharp_total_flow_usdc: float = 0.0
    # Injury Alpha feed inputs (Phase-2d) — attached from a SportsFeed adapter in
    # the strategy. Neutral defaults keep Phase-1/2b callers + tests unchanged and
    # make a NullFeed market inert (injury_present=False → module abstains).
    injury_present: bool = False
    injury_severity: float = 0.0  # [0, 1] magnitude of the event's outcome impact
    injury_detected_age_sec: float = 0.0  # seconds since the event was first observed
    injury_repriced_fraction: float = 0.0  # [0, 1] share of the expected move already absorbed
    injury_yes_favored: bool = False  # True if the event raises P(YES)
    # Public Fade feed inputs (Phase-2e).
    public_pct_on_side: float = 0.0  # [0, 1] share of public tickets on public_side
    public_side: str = ""  # "YES" | "NO" | "" (no public-flow signal)


@dataclass(frozen=True)
class ModuleDecision:
    """A module's verdict for one market."""

    claimed: bool
    side: str = "YES"
    confidence: float = 0.0
    suggested_size_usdc: float = 0.0
    reasoning: str = ""
    tp_pct: float = 0.0
    sl_pct: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def no_claim(cls, reason: str) -> "ModuleDecision":
        """Convenience constructor for a non-claiming decision."""
        return cls(claimed=False, reasoning=reason)


class PlaybookModule(ABC):
    """Base contract every PLAYBOOK module implements.

    Subclasses declare ``name`` (stable id, matches the routing matrix) and the
    ``feed_weights`` they care about, and implement ``evaluate``.
    """

    name: str = ""
    feed_weights: dict[str, float] = {}

    @abstractmethod
    def evaluate(self, snapshot: MarketSnapshot, bundle: SignalBundle) -> ModuleDecision:
        """Decide whether to claim ``snapshot``. Return ``ModuleDecision``."""

    def force_exit_seconds(self) -> float | None:
        """Seconds-to-event at which an open position is force-exited, or None."""
        return None


class ClosingEdgeModule(PlaybookModule):
    """Closing-line value on slow-to-reprice books (Polymarket-native MVP).

    Edge source: thin/medium sports books lag the closing consensus; a side
    purchasable below its fair probability as the event approaches captures
    closing-line value.
    Entry: TTL inside the close window AND a side's (fair - ask) edge ≥ min.
    Exit: force-exit shortly before event start, or TP/SL.
    Risk profile: low–moderate. Holding: minutes (to event close).
    Failure: book reprices against us before exit, or stale fair estimate.
    Best sports: NFL, NHL, NBA (and any thin book near close).
    """

    name = "closing_edge"
    feed_weights = {S.EVENT_TTL: 0.4, S.LIQUIDITY: 0.3, S.LINE_MOVEMENT: 0.3}

    def evaluate(self, snapshot: MarketSnapshot, bundle: SignalBundle) -> ModuleDecision:
        if snapshot.seconds_to_event > CLOSING_EDGE_WINDOW_SEC:
            return ModuleDecision.no_claim("ttl_outside_close_window")
        if not (0.0 < snapshot.fair_price < 1.0):
            return ModuleDecision.no_claim("fair_price_out_of_bounds")

        edge_yes = snapshot.fair_price - snapshot.yes_ask
        edge_no = (1.0 - snapshot.fair_price) - snapshot.no_ask
        if edge_yes >= edge_no:
            side, edge = "YES", edge_yes
        else:
            side, edge = "NO", edge_no

        if edge < CLOSING_EDGE_MIN_EDGE:
            return ModuleDecision.no_claim(f"edge_{edge:.4f}_below_min")

        edge_conf = _clamp01(edge / CLOSING_EDGE_EDGE_SCALE)
        bundle_conf = bundle.weighted_score(self.feed_weights)
        confidence = _clamp01(0.5 * edge_conf + 0.5 * bundle_conf)
        return ModuleDecision(
            claimed=True,
            side=side,
            confidence=confidence,
            suggested_size_usdc=snapshot.suggested_size_usdc,
            reasoning=(
                f"closing_edge: {side} edge {edge:.3f} "
                f"(fair {snapshot.fair_price:.3f}), {snapshot.seconds_to_event:.0f}s to event"
            ),
            tp_pct=CLOSING_EDGE_TP_PCT,
            sl_pct=CLOSING_EDGE_SL_PCT,
            metadata={
                "module": self.name,
                "edge": round(edge, 4),
                "fair_price": snapshot.fair_price,
                "seconds_to_event": snapshot.seconds_to_event,
                "force_exit_at_event_sec": CLOSING_EDGE_FORCE_EXIT_SEC,
            },
        )

    def force_exit_seconds(self) -> float | None:
        return CLOSING_EDGE_FORCE_EXIT_SEC


class SharpMoneyModule(PlaybookModule):
    """On-chain sharp-wallet accumulation (native formula; source live in V2).

    Edge source: persistent one-sided accumulation by historically profitable
    wallets ahead of a move. Entry: sharp imbalance ≥ θ AND TTL > 24h. Phase-1
    returns no claim until the on-chain ``sharp_signed_usdc`` source is wired
    (the formula already lives in ``signals.sharp_money_reading``).
    Best sports: MLB, NHL, Tennis.
    """

    name = "sharp_money"
    feed_weights = {S.SHARP_MONEY: 0.7, S.LINE_MOVEMENT: 0.3}

    def evaluate(self, snapshot: MarketSnapshot, bundle: SignalBundle) -> ModuleDecision:
        # Sharp Money is an EARLY signal — only far from the event (the opposite
        # window to Closing Edge), so the two never compete on one market.
        if snapshot.seconds_to_event <= SHARP_MONEY_MIN_TTL_SEC:
            return ModuleDecision.no_claim("ttl_inside_24h_window")

        reading = bundle.get(S.SHARP_MONEY)
        if reading is None or snapshot.sharp_total_flow_usdc < SHARP_MONEY_MIN_FLOW_USDC:
            return ModuleDecision.no_claim("sharp_flow_below_floor")
        if reading.confidence < SHARP_MONEY_MIN_CONFIDENCE:
            return ModuleDecision.no_claim(
                f"sharp_conf_{reading.confidence:.3f}_below_min"
            )

        # reading.value is the signed imbalance: >0 → sharps accumulating YES.
        side = "YES" if reading.value > 0 else "NO"
        bundle_conf = bundle.weighted_score(self.feed_weights)
        confidence = _clamp01(0.5 * reading.confidence + 0.5 * bundle_conf)
        return ModuleDecision(
            claimed=True,
            side=side,
            confidence=confidence,
            suggested_size_usdc=snapshot.suggested_size_usdc,
            reasoning=(
                f"sharp_money: {side} imbalance {reading.value:+.3f} "
                f"(${snapshot.sharp_signed_usdc:+.0f}/${snapshot.sharp_total_flow_usdc:.0f} "
                f"sharp flow), {snapshot.seconds_to_event / 3600:.1f}h to event"
            ),
            tp_pct=SHARP_MONEY_TP_PCT,
            sl_pct=SHARP_MONEY_SL_PCT,
            metadata={
                "module": self.name,
                "sharp_imbalance": round(reading.value, 4),
                "sharp_signed_usdc": round(snapshot.sharp_signed_usdc, 2),
                "sharp_total_flow_usdc": round(snapshot.sharp_total_flow_usdc, 2),
                "seconds_to_event": snapshot.seconds_to_event,
            },
        )


class PublicFadeModule(PlaybookModule):
    """Fade public overreaction (feed-dependent — Phase-2e).

    Edge source: the public piles onto popular teams/names, pushing a side past
    its fair value; fading the crowded side is contrarian alpha when the public
    lean exceeds the market-implied probability (overreaction). Requires a
    public-flow feed (``SportsFeed.get_public_flow``). Best: UFC, Soccer.

    Entry (blueprint §4): public imbalance ≥ θ AND overreaction (public_pct beats
    the implied prob on that side) AND TTL outside the Closing-Edge window (so the
    two never compete) AND quality OK (enforced upstream). Side traded is the
    OPPOSITE of the public side. Holding: to resolution.
    """

    name = "public_fade"
    feed_weights = {S.PUBLIC_FLOW: 0.6, S.MARKET_SENTIMENT: 0.4}

    def evaluate(self, snapshot: MarketSnapshot, bundle: SignalBundle) -> ModuleDecision:
        pub_side = (snapshot.public_side or "").strip().upper()
        if pub_side not in ("YES", "NO"):
            return ModuleDecision.no_claim("no_public_flow")
        # Contrarian / slow edge — keep clear of Closing Edge's final-window book.
        if snapshot.seconds_to_event <= PUBLIC_FADE_MIN_TTL_SEC:
            return ModuleDecision.no_claim("ttl_inside_closing_window")
        if snapshot.public_pct_on_side < PUBLIC_FADE_MIN_PCT:
            return ModuleDecision.no_claim(
                f"public_pct_{snapshot.public_pct_on_side:.3f}_below_theta"
            )
        if not (0.0 < snapshot.fair_price < 1.0):
            return ModuleDecision.no_claim("fair_price_out_of_bounds")
        # Overreaction: the public bets the side beyond its market-implied probability.
        implied = snapshot.fair_price if pub_side == "YES" else (1.0 - snapshot.fair_price)
        overreaction = snapshot.public_pct_on_side - implied
        if overreaction < PUBLIC_FADE_MIN_OVERREACTION:
            return ModuleDecision.no_claim(f"overreaction_{overreaction:.3f}_below_min")

        reading = bundle.get(S.PUBLIC_FLOW)
        if reading is None or reading.confidence < PUBLIC_FADE_MIN_CONFIDENCE:
            conf = 0.0 if reading is None else reading.confidence
            return ModuleDecision.no_claim(f"public_conf_{conf:.3f}_below_min")

        side = "NO" if pub_side == "YES" else "YES"  # FADE the public
        over_conf = _clamp01(overreaction / PUBLIC_FADE_OVERREACTION_SCALE)
        bundle_conf = bundle.weighted_score(self.feed_weights)
        confidence = _clamp01(0.4 * reading.confidence + 0.3 * over_conf + 0.3 * bundle_conf)
        return ModuleDecision(
            claimed=True,
            side=side,
            confidence=confidence,
            suggested_size_usdc=snapshot.suggested_size_usdc,
            reasoning=(
                f"public_fade: fade {pub_side}→{side}, public {snapshot.public_pct_on_side:.0%} "
                f"vs implied {implied:.0%} (overreaction {overreaction:+.3f}), "
                f"{snapshot.seconds_to_event / 3600:.1f}h to event"
            ),
            tp_pct=PUBLIC_FADE_TP_PCT,
            sl_pct=PUBLIC_FADE_SL_PCT,
            metadata={
                "module": self.name,
                "public_side": pub_side,
                "public_pct_on_side": round(snapshot.public_pct_on_side, 4),
                "implied_prob_public_side": round(implied, 4),
                "overreaction": round(overreaction, 4),
                "seconds_to_event": snapshot.seconds_to_event,
            },
        )


class InjuryAlphaModule(PlaybookModule):
    """Trade the injury/news repricing lag (feed-dependent — Phase-2d).

    Edge source: the window between a confirmed lineup/injury/scratch and the book
    repricing is the highest discrete single-event EV. Requires an injury/news feed
    (``SportsFeed.get_injury_event``). Best: NBA, NFL, Soccer.

    Entry (blueprint §4): an injury/news event detected AND the book not yet
    repriced (``repriced_fraction`` below the cap) AND TTL > 1h (room for the move
    to play out before the event) AND quality OK (enforced upstream). Side is the
    one the event favors (sign of the injury reading). Holding: until repricing or
    the event. Highest precedence in the router — it claims before any native edge.
    """

    name = "injury_alpha"
    feed_weights = {S.NEWS_INJURY: 0.7, S.LINE_MOVEMENT: 0.3}

    def evaluate(self, snapshot: MarketSnapshot, bundle: SignalBundle) -> ModuleDecision:
        if not snapshot.injury_present:
            return ModuleDecision.no_claim("no_injury_event")
        # Need room before the event for the repricing to play out (blueprint TTL>1h).
        if snapshot.seconds_to_event <= INJURY_MIN_TTL_SEC:
            return ModuleDecision.no_claim("ttl_inside_1h_window")
        if snapshot.injury_repriced_fraction >= INJURY_MAX_REPRICED_FRACTION:
            return ModuleDecision.no_claim(
                f"repriced_{snapshot.injury_repriced_fraction:.3f}_edge_gone"
            )

        reading = bundle.get(S.NEWS_INJURY)
        if reading is None or reading.confidence < INJURY_MIN_CONFIDENCE:
            conf = 0.0 if reading is None else reading.confidence
            return ModuleDecision.no_claim(f"injury_conf_{conf:.3f}_below_min")

        # reading.value is signed: >0 → the event favors YES.
        side = "YES" if reading.value > 0 else "NO"
        bundle_conf = bundle.weighted_score(self.feed_weights)
        confidence = _clamp01(0.6 * reading.confidence + 0.4 * bundle_conf)
        return ModuleDecision(
            claimed=True,
            side=side,
            confidence=confidence,
            suggested_size_usdc=snapshot.suggested_size_usdc,
            reasoning=(
                f"injury_alpha: {side} (severity {snapshot.injury_severity:.2f}, "
                f"repriced {snapshot.injury_repriced_fraction:.0%}, "
                f"age {snapshot.injury_detected_age_sec:.0f}s), "
                f"{snapshot.seconds_to_event / 3600:.1f}h to event"
            ),
            tp_pct=INJURY_TP_PCT,
            sl_pct=INJURY_SL_PCT,
            metadata={
                "module": self.name,
                "injury_severity": round(snapshot.injury_severity, 4),
                "injury_repriced_fraction": round(snapshot.injury_repriced_fraction, 4),
                "injury_detected_age_sec": round(snapshot.injury_detected_age_sec, 1),
                "injury_yes_favored": snapshot.injury_yes_favored,
                "seconds_to_event": snapshot.seconds_to_event,
            },
        )


__all__ = [
    "MarketSnapshot",
    "ModuleDecision",
    "PlaybookModule",
    "ClosingEdgeModule",
    "SharpMoneyModule",
    "PublicFadeModule",
    "InjuryAlphaModule",
]
