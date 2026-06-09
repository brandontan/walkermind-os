"""PLAYBOOK signal layer.

Computes a bundle of ``SignalReading``s from a market snapshot. Each reading
carries a ``confidence`` in [0, 1] and a ``native`` flag distinguishing
Polymarket-native signals (live in Phase-1) from feed-dependent ones (neutral
until their ``SportsFeed`` adapter is wired in V2).

Pure functions — no DB, no async, no network. The caller assembles the market
snapshot (from the existing Polymarket integration) and passes primitives in.
See ``docs/blueprint/playbook.md`` §3 for the feed catalogue and weighting.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Signal feed identifiers (stable keys used in the weighting model + metadata).
LINE_MOVEMENT = "line_movement"
SHARP_MONEY = "sharp_money"
PUBLIC_FLOW = "public_flow"
NEWS_INJURY = "news_injury"
LIQUIDITY = "liquidity"
EVENT_TTL = "event_ttl"
TEAM_STRENGTH = "team_strength"
MARKET_SENTIMENT = "market_sentiment"

# Native-now feeds computable from Polymarket orderbook / on-chain data alone.
NATIVE_FEEDS: frozenset[str] = frozenset(
    {LINE_MOVEMENT, SHARP_MONEY, LIQUIDITY, EVENT_TTL, MARKET_SENTIMENT}
)


def _clamp01(x: float) -> float:
    """Clamp a float into [0.0, 1.0]."""
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


@dataclass(frozen=True)
class SignalReading:
    """A single feed's reading for one market.

    ``value`` is the feed's natural (signed) magnitude; ``confidence`` is the
    [0, 1] strength used by the router's weighting. ``native`` marks whether
    the reading came from a Polymarket-native computation (True) or an external
    feed / neutral fallback (False).
    """

    feed: str
    value: float
    confidence: float
    native: bool
    detail: str = ""

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"SignalReading.confidence must be in [0,1], got {self.confidence}"
            )
        if not self.feed:
            raise ValueError("SignalReading.feed must be non-empty")


@dataclass(frozen=True)
class SignalBundle:
    """All feed readings for one market, keyed by feed id."""

    market_id: str
    readings: dict[str, SignalReading] = field(default_factory=dict)

    def get(self, feed: str) -> SignalReading | None:
        """Return the reading for ``feed`` or None if not present."""
        return self.readings.get(feed)

    def weighted_score(self, weights: dict[str, float]) -> float:
        """Return Σ wᵢ·confidenceᵢ over the feeds named in ``weights``.

        Feeds absent from the bundle contribute 0. The result is normalised by
        the total weight so the score stays in [0, 1] regardless of how many
        feeds a module weights.
        """
        total_w = sum(weights.values())
        if total_w <= 0:
            return 0.0
        acc = 0.0
        for feed, w in weights.items():
            r = self.readings.get(feed)
            if r is not None:
                acc += w * r.confidence
        return _clamp01(acc / total_w)


# ---------------------------------------------------------------------------
# Native feed formulas (Phase-1)
# ---------------------------------------------------------------------------


def line_movement_reading(
    mid_now: float, mid_prev: float, noise_sigma: float
) -> SignalReading:
    """Δmid over the lookback window measured in noise-sigma units.

    confidence = |Δmid / σ| clamped to [0,1]; value carries the signed move so
    a module can read direction. ``noise_sigma <= 0`` → zero-confidence.
    """
    if noise_sigma <= 0:
        return SignalReading(LINE_MOVEMENT, 0.0, 0.0, native=True, detail="sigma<=0")
    delta = mid_now - mid_prev
    conf = _clamp01(abs(delta) / noise_sigma)
    return SignalReading(
        LINE_MOVEMENT, delta, conf, native=True, detail=f"delta={delta:.4f}"
    )


def liquidity_reading(
    liquidity_usdc: float, spread: float, liq_ref_usdc: float = 25_000.0
) -> SignalReading:
    """Liquidity quality: deep + tight book → high confidence.

    confidence blends depth (liquidity/ref, capped at 1) and tightness
    (1 - spread, floored at 0), averaged. Higher = healthier book to trade.
    """
    depth_score = _clamp01(liquidity_usdc / liq_ref_usdc) if liq_ref_usdc > 0 else 0.0
    tight_score = _clamp01(1.0 - max(0.0, spread))
    conf = _clamp01(0.5 * depth_score + 0.5 * tight_score)
    return SignalReading(
        LIQUIDITY, liquidity_usdc, conf, native=True, detail=f"spread={spread:.4f}"
    )


def event_ttl_reading(seconds_to_event: float, close_window_sec: float) -> SignalReading:
    """Event time-to-live as a closing-proximity confidence.

    confidence rises as the event approaches: 0 when far, 1 inside the close
    window. value carries raw seconds so modules can branch on TTL buckets.
    """
    if seconds_to_event <= 0:
        return SignalReading(EVENT_TTL, 0.0, 1.0, native=True, detail="at_or_past")
    if close_window_sec <= 0:
        return SignalReading(EVENT_TTL, seconds_to_event, 0.0, native=True)
    conf = _clamp01(1.0 - (seconds_to_event / close_window_sec)) if (
        seconds_to_event < close_window_sec
    ) else 0.0
    return SignalReading(
        EVENT_TTL, seconds_to_event, conf, native=True, detail=f"ttl={seconds_to_event:.0f}s"
    )


def market_sentiment_reading(buy_flow_usdc: float, sell_flow_usdc: float) -> SignalReading:
    """Order-flow skew: |buy - sell| / (buy + sell) as confidence.

    value is signed (positive = net buy / YES-lean). ``total<=0`` → neutral.
    """
    total = buy_flow_usdc + sell_flow_usdc
    if total <= 0:
        return SignalReading(MARKET_SENTIMENT, 0.0, 0.0, native=True, detail="no_flow")
    skew = (buy_flow_usdc - sell_flow_usdc) / total
    return SignalReading(
        MARKET_SENTIMENT, skew, _clamp01(abs(skew)), native=True, detail=f"skew={skew:.3f}"
    )


def sharp_money_reading(
    sharp_signed_usdc: float, total_flow_usdc: float, sharp_pnl_weight: float = 1.0
) -> SignalReading:
    """On-chain sharp-wallet accumulation imbalance.

    confidence = |sharp_signed / total| × pnl_weight, clamped. value signed so
    a module can read which side the sharps are accumulating. Phase-1 ships the
    formula; the on-chain ``sharp_signed_usdc`` source is promoted from proxy
    to live in V2 (reuses the copy-trade chain monitor).
    """
    if total_flow_usdc <= 0:
        return SignalReading(SHARP_MONEY, 0.0, 0.0, native=True, detail="no_flow")
    imbalance = sharp_signed_usdc / total_flow_usdc
    conf = _clamp01(abs(imbalance) * max(0.0, sharp_pnl_weight))
    return SignalReading(
        SHARP_MONEY, imbalance, conf, native=True, detail=f"imbalance={imbalance:.3f}"
    )


def news_injury_reading(
    *,
    present: bool,
    severity: float,
    detected_age_sec: float,
    repriced_fraction: float,
    yes_favored: bool,
    max_age_sec: float = 3_600.0,
) -> SignalReading:
    """Injury / news repricing-lag reading (feed-dependent, Phase-2d).

    Blueprint §3 feed #4: ``recency × severity`` while the book has not yet
    repriced. ``confidence = severity · recency · unrepriced`` where
    ``recency = 1 - age/max_age`` (a stale event has decayed) and
    ``unrepriced = 1 - repriced_fraction`` (an already-absorbed event has no
    edge left). ``value`` is signed — positive when the event favors YES — so
    ``InjuryAlphaModule`` reads the side to buy from the sign. ``native=False``:
    the reading is only as good as the external feed that supplied it.

    No event (``present=False``) or zero severity → neutral zero-confidence
    reading, identical to the Phase-1 placeholder so a NullFeed market is inert.
    """
    if not present or severity <= 0.0:
        return SignalReading(NEWS_INJURY, 0.0, 0.0, native=False, detail="no_event")
    recency = _clamp01(1.0 - detected_age_sec / max_age_sec) if max_age_sec > 0 else 0.0
    unrepriced = _clamp01(1.0 - repriced_fraction)
    conf = _clamp01(_clamp01(severity) * recency * unrepriced)
    sign = 1.0 if yes_favored else -1.0
    return SignalReading(
        NEWS_INJURY,
        sign * conf,
        conf,
        native=False,
        detail=f"sev={severity:.2f} age={detected_age_sec:.0f}s repriced={repriced_fraction:.2f}",
    )


def public_flow_reading(*, public_pct_on_side: float, side: str) -> SignalReading:
    """Public-betting imbalance reading (feed-dependent, Phase-2e).

    Blueprint §3 feed #3: divergence magnitude of the public lean. ``confidence``
    scales the lopsidedness of public tickets, ``2·|pct − 0.5|`` clamped (an even
    50/50 split is zero-confidence, a 100% pile is full). ``value`` is signed
    toward the **public** side (positive = public on YES); ``PublicFadeModule``
    trades the *opposite* side. ``native=False`` — external feed quality bound.

    No flow (``side`` not YES/NO, or zero pct) → neutral, matching the Phase-1
    placeholder so a NullFeed market stays inert.
    """
    s = (side or "").strip().upper()
    if s not in ("YES", "NO") or public_pct_on_side <= 0.0:
        return SignalReading(PUBLIC_FLOW, 0.0, 0.0, native=False, detail="no_flow")
    conf = _clamp01(2.0 * abs(public_pct_on_side - 0.5))
    sign = 1.0 if s == "YES" else -1.0
    return SignalReading(
        PUBLIC_FLOW,
        sign * conf,
        conf,
        native=False,
        detail=f"pub%={public_pct_on_side:.2f} on {s}",
    )


def neutral_reading(feed: str) -> SignalReading:
    """Zero-confidence reading for a feed-dependent signal with no adapter."""
    return SignalReading(feed, 0.0, 0.0, native=False, detail="no_feed")


def compute_signal_bundle(
    *,
    market_id: str,
    mid_now: float,
    mid_prev: float,
    noise_sigma: float,
    liquidity_usdc: float,
    spread: float,
    seconds_to_event: float,
    close_window_sec: float,
    buy_flow_usdc: float,
    sell_flow_usdc: float,
    sharp_signed_usdc: float,
    total_flow_usdc: float,
    # Feed-dependent inputs (Phase-2d/2e). Default-neutral so Phase-1/2b callers
    # and a NullFeed market produce exactly the Phase-1 placeholder readings.
    injury_present: bool = False,
    injury_severity: float = 0.0,
    injury_detected_age_sec: float = 0.0,
    injury_repriced_fraction: float = 0.0,
    injury_yes_favored: bool = False,
    public_pct_on_side: float = 0.0,
    public_side: str = "",
) -> SignalBundle:
    """Assemble all readings into a bundle for one market.

    Native feeds are computed from the orderbook / on-chain inputs. Feed-dependent
    signals (public flow, news/injury) are now adapter-backed: when the caller
    supplies feed data they produce live readings, otherwise they fall back to a
    neutral reading internally (so the bundle always exposes the full feed set and
    a NullFeed market is inert). Team strength remains a neutral placeholder (V3).
    """
    readings: dict[str, SignalReading] = {}
    readings[LINE_MOVEMENT] = line_movement_reading(mid_now, mid_prev, noise_sigma)
    readings[LIQUIDITY] = liquidity_reading(liquidity_usdc, spread)
    readings[EVENT_TTL] = event_ttl_reading(seconds_to_event, close_window_sec)
    readings[MARKET_SENTIMENT] = market_sentiment_reading(buy_flow_usdc, sell_flow_usdc)
    readings[SHARP_MONEY] = sharp_money_reading(sharp_signed_usdc, total_flow_usdc)
    readings[NEWS_INJURY] = news_injury_reading(
        present=injury_present,
        severity=injury_severity,
        detected_age_sec=injury_detected_age_sec,
        repriced_fraction=injury_repriced_fraction,
        yes_favored=injury_yes_favored,
    )
    readings[PUBLIC_FLOW] = public_flow_reading(
        public_pct_on_side=public_pct_on_side, side=public_side
    )
    readings[TEAM_STRENGTH] = neutral_reading(TEAM_STRENGTH)
    return SignalBundle(market_id=market_id, readings=readings)


__all__ = [
    "SignalReading",
    "SignalBundle",
    "compute_signal_bundle",
    "line_movement_reading",
    "liquidity_reading",
    "event_ttl_reading",
    "market_sentiment_reading",
    "sharp_money_reading",
    "news_injury_reading",
    "public_flow_reading",
    "neutral_reading",
    "NATIVE_FEEDS",
    "LINE_MOVEMENT",
    "SHARP_MONEY",
    "PUBLIC_FLOW",
    "NEWS_INJURY",
    "LIQUIDITY",
    "EVENT_TTL",
    "TEAM_STRENGTH",
    "MARKET_SENTIMENT",
]
