"""Phase 10 — ArbDetector: Polymarket vs Kalshi arbitrage signal generator.

Detects price discrepancies between Polymarket and Kalshi for the same
underlying event.  When the spread exceeds the configured threshold a
structured signal is emitted.

**No execution is performed here.**  Signals are data-only; the caller
decides whether to act on them.

Market matching::

    Markets are correlated by ``keyword`` overlap in their title / question
    text.  Exact ticker mapping can be injected via the ``market_map``
    parameter for precision matching.

Signal schema::

    {
        "polymarket_id":  str,
        "kalshi_ticker":  str,
        "polymarket_yes": float,   # normalised 0–1
        "kalshi_yes":     float,   # normalised 0–1
        "spread":         float,   # abs difference
        "direction":      "BUY_POLY" | "BUY_KALSHI",
        "threshold":      float,
        "timestamp":      float,   # Unix epoch seconds
        "_type":          "arb_signal"
    }

Usage::

    detector = ArbDetector.from_config(config)
    signals = detector.detect(
        polymarket_markets=[{"id": "0xabc", "yes_price": 0.65, "title": "..."}],
        kalshi_markets=[{"ticker": "PRES-REP", "yes_price": 0.58, "title": "..."}],
    )
    for signal in signals:
        log.info("arb_signal_detected", **signal)

Thread-safety: single asyncio event loop (all methods are synchronous).
"""
from __future__ import annotations

import time
from typing import Optional

import structlog

log = structlog.get_logger()

# ── Defaults ──────────────────────────────────────────────────────────────────

_DEFAULT_SPREAD_THRESHOLD: float = 0.04   # 4 percentage-point spread
_DEFAULT_MIN_OVERLAP_WORDS: int = 2        # keyword matching


# ── ArbDetector ───────────────────────────────────────────────────────────────


class ArbDetector:
    """Detects arbitrage opportunities between Polymarket and Kalshi.

    The detector is stateless — it does not cache prior signals or track
    position state.  All detection logic is pure input/output.

    Args:
        spread_threshold: Minimum price spread (absolute, 0–1 scale) required
                          to emit a signal.
        min_overlap_words: Minimum number of common title words required to
                           consider two markets as matching the same event.
        market_map: Optional explicit mapping from Polymarket condition ID to
                    Kalshi ticker for exact matching.  When provided, fuzzy
                    title matching is used only for unmapped markets.
    """

    def __init__(
        self,
        spread_threshold: float = _DEFAULT_SPREAD_THRESHOLD,
        min_overlap_words: int = _DEFAULT_MIN_OVERLAP_WORDS,
        market_map: Optional[dict[str, str]] = None,
    ) -> None:
        self._spread_threshold = spread_threshold
        self._min_overlap_words = min_overlap_words
        self._market_map: dict[str, str] = market_map or {}

        log.info(
            "arb_detector_initialized",
            spread_threshold=spread_threshold,
            min_overlap_words=min_overlap_words,
            market_map_entries=len(self._market_map),
        )

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_config(cls, config: dict) -> "ArbDetector":
        """Build from configuration dict.

        Args:
            config: Top-level config dict.  Reads ``arb_detector`` sub-key.

        Returns:
            Configured ArbDetector.
        """
        cfg = config.get("arb_detector", {})
        return cls(
            spread_threshold=float(cfg.get("spread_threshold", _DEFAULT_SPREAD_THRESHOLD)),
            min_overlap_words=int(cfg.get("min_overlap_words", _DEFAULT_MIN_OVERLAP_WORDS)),
            market_map=dict(cfg.get("market_map", {})),
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def detect(
        self,
        polymarket_markets: list[dict],
        kalshi_markets: list[dict],
    ) -> list[dict]:
        """Detect arbitrage signals from two market snapshots.

        Args:
            polymarket_markets: List of Polymarket market dicts, each must
                contain at minimum ``id``, ``yes_price``, and ``title`` (or
                ``question``) keys.
            kalshi_markets: List of Kalshi market dicts produced by
                :class:`connectors.kalshi_client.KalshiClient` (normalised).

        Returns:
            List of signal dicts (may be empty).  Each signal contains the
            fields described in the module docstring.
        """
        if not polymarket_markets or not kalshi_markets:
            return []

        # Build a fast lookup from Kalshi ticker → market dict
        kalshi_by_ticker: dict[str, dict] = {
            m["ticker"]: m for m in kalshi_markets if m.get("ticker")
        }

        signals: list[dict] = []

        for poly_market in polymarket_markets:
            try:
                signal = self._check_market(poly_market, kalshi_by_ticker, kalshi_markets)
                if signal is not None:
                    signals.append(signal)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "arb_detector_market_check_error",
                    market_id=poly_market.get("id", "unknown"),
                    error=str(exc),
                )

        log.info(
            "arb_detector_scan_complete",
            poly_markets=len(polymarket_markets),
            kalshi_markets=len(kalshi_markets),
            signals_found=len(signals),
            threshold=self._spread_threshold,
        )

        return signals

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _check_market(
        self,
        poly_market: dict,
        kalshi_by_ticker: dict[str, dict],
        kalshi_markets: list[dict],
    ) -> Optional[dict]:
        """Check a single Polymarket market against Kalshi.

        Args:
            poly_market: Normalised Polymarket market dict.
            kalshi_by_ticker: Kalshi markets indexed by ticker.
            kalshi_markets: Full list of Kalshi markets (for fuzzy matching).

        Returns:
            Signal dict if spread exceeds threshold, else ``None``.
        """
        poly_id: str = str(poly_market.get("id", ""))
        poly_yes: float = float(poly_market.get("yes_price", 0.0) or 0.0)
        poly_title: str = str(
            poly_market.get("title", poly_market.get("question", ""))
        ).lower()

        # ── Attempt exact mapping first ───────────────────────────────────────
        kalshi_market: Optional[dict] = None
        if poly_id in self._market_map:
            ticker = self._market_map[poly_id]
            kalshi_market = kalshi_by_ticker.get(ticker)

        # ── Fallback: fuzzy title match ───────────────────────────────────────
        if kalshi_market is None and poly_title:
            kalshi_market = self._fuzzy_match(poly_title, kalshi_markets)

        if kalshi_market is None:
            return None

        kalshi_yes: float = float(kalshi_market.get("yes_price", 0.0) or 0.0)
        spread: float = abs(poly_yes - kalshi_yes)

        if spread < self._spread_threshold:
            return None

        direction = "BUY_POLY" if poly_yes < kalshi_yes else "BUY_KALSHI"

        signal: dict = {
            "polymarket_id": poly_id,
            "kalshi_ticker": str(kalshi_market.get("ticker", "")),
            "polymarket_yes": round(poly_yes, 6),
            "kalshi_yes": round(kalshi_yes, 6),
            "spread": round(spread, 6),
            "direction": direction,
            "threshold": self._spread_threshold,
            "timestamp": time.time(),
            "_type": "arb_signal",
        }

        log.info(
            "arb_signal_detected",
            polymarket_id=poly_id,
            kalshi_ticker=signal["kalshi_ticker"],
            spread=signal["spread"],
            direction=direction,
        )

        return signal

    def _fuzzy_match(
        self,
        poly_title_lower: str,
        kalshi_markets: list[dict],
    ) -> Optional[dict]:
        """Find the best-matching Kalshi market by title word overlap.

        Args:
            poly_title_lower: Lowercased Polymarket title.
            kalshi_markets: All Kalshi markets.

        Returns:
            Best-matching Kalshi market dict, or ``None`` if no match meets
            the ``min_overlap_words`` threshold.
        """
        poly_words = set(self._tokenize(poly_title_lower))

        best_match: Optional[dict] = None
        best_overlap: int = 0

        for km in kalshi_markets:
            kalshi_title = str(km.get("title", "")).lower()
            kalshi_words = set(self._tokenize(kalshi_title))
            overlap = len(poly_words & kalshi_words)

            if overlap >= self._min_overlap_words and overlap > best_overlap:
                best_overlap = overlap
                best_match = km

        return best_match

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Simple whitespace + punctuation tokenizer.

        Args:
            text: Input text.

        Returns:
            List of lowercase alphanumeric tokens (length >= 3).
        """
        import re
        return [w for w in re.split(r"[^a-z0-9]+", text) if len(w) >= 3]
