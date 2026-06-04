"""Multi-asset crypto oracle via the Polymarket Real-Time Data Stream (RTDS).

Reads the live oracle price the Polymarket crypto up/down candle markets resolve
against — Chainlink Data Streams (BTC/USD, ETH/USD, SOL/USD) — through
Polymarket's own RTDS WebSocket ``wss://ws-live-data.polymarket.com``. Using the
exchange's stream means **no separate Chainlink Data Streams credentials** and
the exact same number the market settles on (never Binance/Coinbase spot, whose
basis difference decides win/loss in the final seconds).

Foundation layer (WARP-62, Chunk 1/4): this module ONLY streams the live price,
keyed by asset symbol, and captures the candle-open reference (see
``price_to_beat``). It does NOT compute fair value or wire into any strategy
(Chunks 2/3). The oracle is multi-asset by construction — one client, many feeds
(BTC/ETH/SOL today, extensible via the ``ORACLE_SYMBOLS`` config map) — and is
gated behind the ``ORACLE_ENABLED`` feature flag (default OFF).

Design (mirrors ``integrations/clob/ws.py``):
  * Single long-lived connection, reconnect with exponential backoff + jitter.
  * Injectable ``connect_factory`` seam so unit tests drive a fake socket with
    canned frames — no network is ever opened in tests.
  * Per-symbol price cache stamped with a monotonic read time.
  * **Staleness is honest**: ``get_price`` returns ``None`` (and logs) when the
    latest tick for a symbol is older than ``staleness_sec`` — a stale price is
    NEVER returned as if it were live. No silent failures.

The RTDS subscribe/message wire-format is isolated in
``_build_subscribe_frame`` / ``_parse_tick``. It has been verified against a
live raw-frame dump (2026-06-04): the Chainlink feed is the
``crypto_prices_chainlink`` topic, subscribed with ``type: "*"`` and a
string ``filters`` (broadcast-all, scoped client-side), and each tick carries
``payload.value`` (USD float) plus ``payload.symbol`` (lowercase ``btc/usd``).
The parser stays defensive: it tolerates acks/empty frames and only updates
configured symbols.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import random
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Deque, Iterable, Optional, Tuple

import structlog

from ....config import get_settings

log = structlog.get_logger(__name__)

# url -> connected websocket object (async-iterable, with .send()/.close()).
ConnectFactory = Callable[[str], Awaitable[Any]]

_DEFAULT_QUOTE = "usd"
_INITIAL_BACKOFF_SEC = 1.0
_MAX_BACKOFF_SEC = 30.0
# Rolling history ring (WARP-68): derive the candle-open price_to_beat from our
# own Chainlink feed at eventStartTime. 30 min covers the longest candle (15m) +
# jitter margin; the hard maxlen is a safety cap (>30 min even at 1 Hz).
_DEFAULT_HISTORY_WINDOW_SEC = 1800.0
_HISTORY_MAXLEN = 4000
# Nearest-tick match window: Chainlink reports at 1 Hz aligned to whole seconds,
# so the open tick sits within ~1 s of the open epoch. Beyond this -> honest miss
# (a far/stale tick is never substituted for the true open).
_DEFAULT_PTB_TOLERANCE_SEC = 2.0
# Plausible epoch bands (~2020..2033) used to sanity-check and unit-normalize the
# Chainlink report timestamp before it seeds the history ring. A wrong-scale or
# garbage timestamp must NEVER reach the ring: the ring is time-pruned off the
# newest tick's own ts (cutoff = ts - window), so a far-future garbage value would
# evict every legitimate tick. Seconds are normalized to ms; anything outside both
# bands is dropped (the tick still updates the live cache, just not the history).
_TS_MIN_SEC = 1_600_000_000.0
_TS_MAX_SEC = 2_000_000_000.0
_TS_MIN_MS = 1_600_000_000_000.0
_TS_MAX_MS = 2_000_000_000_000.0


def _normalize_ts_ms(raw: Any) -> Optional[float]:
    """Coerce a frame timestamp to milliseconds within a sane epoch band, else None.

    Accepts ms directly, normalizes a seconds-scale value to ms, and rejects
    NaN/inf/non-numeric/out-of-band values so the history ring's prune anchor can
    never be corrupted by a bad timestamp.
    """
    if raw is None or isinstance(raw, bool):
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if v != v or v in (float("inf"), float("-inf")):  # NaN / inf
        return None
    if _TS_MIN_SEC <= v <= _TS_MAX_SEC:  # seconds -> ms
        v *= 1000.0
    if _TS_MIN_MS <= v <= _TS_MAX_MS:
        return v
    return None


class OracleError(RuntimeError):
    """Base class for all oracle failures (no silent fabrication)."""


class OracleDisabledError(OracleError):
    """Raised when a runtime entrypoint is used while ORACLE_ENABLED is OFF."""


class OracleConfigError(OracleError):
    """Raised when required oracle config (symbols / url) is missing."""


def normalize_symbol(symbol: str) -> str:
    """Canonicalise a symbol to ``base/quote`` lowercase.

    Accepts a bare ticker (``"BTC"`` -> ``"btc/usd"``), a slash pair
    (``"ETH/USD"`` -> ``"eth/usd"``), or a dash pair (``"sol-usd"`` ->
    ``"sol/usd"``) so callers can pass either ``get_price("btc")`` or the full
    RTDS pair.
    """
    s = str(symbol).strip().lower().replace("-", "/")
    if "/" not in s:
        s = f"{s}/{_DEFAULT_QUOTE}"
    return s


def parse_symbols(raw: str | Iterable[str]) -> list[str]:
    """Parse the configured symbol map (CSV or iterable) to normalized pairs.

    Preserves order, drops blanks, de-duplicates. ``"btc/usd, eth/usd"`` ->
    ``["btc/usd", "eth/usd"]``.
    """
    items: Iterable[str]
    items = raw.split(",") if isinstance(raw, str) else raw
    out: list[str] = []
    for item in items:
        norm = normalize_symbol(item)
        if norm.startswith("/") or norm.endswith("/"):
            continue
        if norm not in out:
            out.append(norm)
    return out


def _backoff_delay(attempt: int, *, max_delay: float) -> float:
    """Exponential backoff with full jitter, capped at ``max_delay``."""
    base = min(_INITIAL_BACKOFF_SEC * (2 ** max(0, attempt - 1)), max_delay)
    return random.uniform(0.0, base)


@dataclass(frozen=True)
class _Tick:
    price: float
    at_monotonic: float


class PolymarketRTDSOracle:
    """Streaming multi-asset crypto price oracle (Polymarket RTDS).

    Construct directly with an injected ``connect_factory`` (tests) or via
    :func:`oracle_from_settings` (flag-gated runtime). Call :meth:`start` to open
    the stream and :meth:`get_price` to read the latest fresh price for a symbol.
    """

    def __init__(
        self,
        *,
        ws_url: str,
        symbols: Iterable[str],
        staleness_sec: float = 10.0,
        connect_factory: Optional[ConnectFactory] = None,
        clock: Callable[[], float] = time.monotonic,
        max_backoff_sec: float = _MAX_BACKOFF_SEC,
        history_window_sec: float = _DEFAULT_HISTORY_WINDOW_SEC,
    ) -> None:
        symbols = parse_symbols(list(symbols))
        if not ws_url:
            raise OracleConfigError("RTDS ws_url missing")
        if not symbols:
            raise OracleConfigError("no oracle symbols configured")
        self._ws_url = ws_url
        self._symbols = symbols
        self._symbol_set = set(symbols)
        self._staleness_sec = float(staleness_sec)
        self._connect_factory = connect_factory
        self._clock = clock
        self._max_backoff_sec = float(max_backoff_sec)
        self._history_window_ms = float(history_window_sec) * 1000.0

        self._ticks: dict[str, _Tick] = {}
        # Per-symbol time-ordered ring of (chainlink_report_ms, price) for the
        # candle-open lookup (price_at). Keyed by normalized symbol.
        self._history: dict[str, Deque[Tuple[float, float]]] = {
            sym: deque(maxlen=_HISTORY_MAXLEN) for sym in symbols
        }
        self._ws: Any = None
        self._run_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._connected_event = asyncio.Event()
        self._connect_attempts = 0

    # ----- public surface --------------------------------------------------

    @property
    def symbols(self) -> list[str]:
        return list(self._symbols)

    def get_price(self, symbol: str) -> Optional[float]:
        """Latest live price for ``symbol`` (USD float), or ``None``.

        Returns ``None`` — never a stale number — when the symbol has no tick yet
        or its newest tick is older than ``staleness_sec``. The staleness drop is
        logged so a starved feed is visible, not silent.
        """
        key = normalize_symbol(symbol)
        tick = self._ticks.get(key)
        if tick is None:
            return None
        age = self._clock() - tick.at_monotonic
        if age > self._staleness_sec:
            log.warning(
                "rtds oracle price stale",
                symbol=key, age_sec=round(age, 3), threshold=self._staleness_sec,
            )
            return None
        return tick.price

    def is_stale(self, symbol: str) -> bool:
        """True when ``get_price`` would refuse the symbol (missing or stale)."""
        key = normalize_symbol(symbol)
        tick = self._ticks.get(key)
        if tick is None:
            return True
        return (self._clock() - tick.at_monotonic) > self._staleness_sec

    def price_at(
        self,
        symbol: str,
        epoch_sec: float,
        *,
        tolerance_sec: float = _DEFAULT_PTB_TOLERANCE_SEC,
    ) -> Optional[float]:
        """Chainlink price nearest the candle-open ``epoch_sec`` (unix seconds), or None.

        Scans the per-symbol history ring for the tick whose Chainlink report
        time is closest to ``epoch_sec`` and returns its price ONLY if within
        ``tolerance_sec``. This is the ``price_to_beat`` baseline: same Chainlink
        source as :meth:`get_price` (``oracle_now``), so delta is basis-clean.

        Honest by construction — returns ``None`` (never a far/stale tick) when:
          * the symbol has no buffered tick within tolerance, or
          * the candle open predates the connection (cold start), or
          * the open is outside the retained window.
        A wrong open silently corrupts delta near close, so a miss is preferred
        over a fabricated baseline.
        """
        key = normalize_symbol(symbol)
        ring = self._history.get(key)
        if not ring:
            return None
        target_ms = float(epoch_sec) * 1000.0
        tol_ms = float(tolerance_sec) * 1000.0
        best_price: Optional[float] = None
        best_dist: Optional[float] = None
        for ts_ms, price in ring:
            dist = abs(ts_ms - target_ms)
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best_price = price
        if best_dist is None or best_dist > tol_ms:
            return None
        return best_price

    async def start(self) -> None:
        """Open the stream in a background task (idempotent)."""
        if self._run_task is not None and not self._run_task.done():
            return
        self._stop_event.clear()
        self._connect_attempts = 0
        self._run_task = asyncio.create_task(
            self._run_loop(), name="rtds-oracle",
        )

    async def stop(self) -> None:
        """Signal stop, close the socket, and await the background task."""
        self._stop_event.set()
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.close()
            self._ws = None
        if self._run_task is not None:
            self._run_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._run_task
            self._run_task = None
        self._connected_event.clear()

    async def wait_connected(self, timeout: float = 5.0) -> bool:
        """Block until the socket is open (or timeout). Test/operator helper."""
        try:
            await asyncio.wait_for(self._connected_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    # ----- internals -------------------------------------------------------

    async def _run_loop(self) -> None:
        """Outer connect-with-backoff loop; reconnects until stopped."""
        while not self._stop_event.is_set():
            self._connect_attempts += 1
            if self._connect_attempts > 1:
                delay = _backoff_delay(
                    self._connect_attempts - 1, max_delay=self._max_backoff_sec,
                )
                log.info("rtds oracle reconnect", attempt=self._connect_attempts,
                         delay_sec=round(delay, 3))
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
                    return  # stop signalled during backoff
                except asyncio.TimeoutError:
                    pass
            try:
                await self._connect_and_read()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — contained, logged, retried
                log.warning("rtds oracle session error", err=str(exc))
            else:
                log.info("rtds oracle session ended")

    async def _connect_and_read(self) -> None:
        """One socket lifetime: open, subscribe, drain frames, close."""
        ws = await self._open_connection()
        self._ws = ws
        self._connect_attempts = 1  # reset ramp on a clean open
        self._connected_event.set()
        try:
            await ws.send(json.dumps(self._build_subscribe_frame()))
            async for raw in ws:
                if self._stop_event.is_set():
                    break
                self._handle_message(raw)
        finally:
            with contextlib.suppress(Exception):
                await ws.close()
            self._ws = None
            self._connected_event.clear()

    async def _open_connection(self) -> Any:
        """Open the socket via the injected factory or ``websockets.connect``."""
        if self._connect_factory is not None:
            return await self._connect_factory(self._ws_url)
        try:
            import websockets  # type: ignore
        except ImportError as exc:  # pragma: no cover - missing-dep path
            raise OracleConfigError(
                "websockets package not installed; add to pyproject.toml"
            ) from exc
        return await websockets.connect(self._ws_url, close_timeout=5)

    def _build_subscribe_frame(self) -> dict[str, Any]:
        """Build the RTDS subscribe payload for the Chainlink crypto feed.

        Wire-format verified against a live ``wss://ws-live-data.polymarket.com``
        raw-frame dump (2026-06-04):

          * topic ``crypto_prices_chainlink`` — the **Chainlink** oracle feed the
            up/down candle markets resolve against (the bare ``crypto_prices``
            topic is the Binance source and is WRONG for resolution).
          * ``type: "*"`` — subscribe to all message types on the topic (ticks
            arrive back stamped ``type: "update"``).
          * ``filters`` MUST be a **string**; ``""`` subscribes to every symbol.
            A filters *object* is rejected by the server ("Invalid request
            body"), so we broadcast-subscribe and scope client-side: the
            per-symbol map (``self._symbol_set``) is enforced in
            :meth:`_parse_tick`, which drops any symbol outside the configured
            set. This keeps the BTC/ETH/SOL symbol-map abstraction intact while
            using the only filter shape the server accepts.
        """
        return {
            "action": "subscribe",
            "subscriptions": [
                {"topic": "crypto_prices_chainlink", "type": "*", "filters": ""},
            ],
        }

    def _handle_message(self, raw: Any) -> None:
        """Decode one frame and update the price cache (per-message containment).

        A malformed/unrelated frame is logged at debug and dropped — it must
        never crash the read loop or corrupt the cache.
        """
        try:
            msg = raw if isinstance(raw, dict) else json.loads(raw)
        except (TypeError, ValueError) as exc:
            log.debug("rtds oracle bad frame", err=str(exc))
            return
        parsed = self._parse_tick(msg)
        if parsed is None:
            return
        symbol, price, ts_ms = parsed
        self._ticks[symbol] = _Tick(price=price, at_monotonic=self._clock())
        if ts_ms is not None:
            self._record_history(symbol, ts_ms, price)
        log.debug("rtds oracle tick", symbol=symbol, price=price)

    def _record_history(self, symbol: str, ts_ms: float, price: float) -> None:
        """Append a tick to the symbol ring and time-prune the window.

        Pruning is anchored on the newest tick's own Chainlink report time (not
        a local clock), so the retained window is exactly ``history_window_sec``
        of wall-clock Chainlink data regardless of host clock skew.
        """
        ring = self._history.get(symbol)
        if ring is None:
            return
        ring.append((ts_ms, price))
        cutoff = ts_ms - self._history_window_ms
        while ring and ring[0][0] < cutoff:
            ring.popleft()

    def _parse_tick(
        self, msg: dict[str, Any]
    ) -> Optional[tuple[str, float, Optional[float]]]:
        """Extract ``(normalized_symbol, price, chainlink_report_ms)`` from a frame.

        Verified ``crypto_prices_chainlink`` frame shape (live, 2026-06-04)::

            {"topic": "crypto_prices_chainlink", "type": "update",
             "payload": {"symbol": "btc/usd", "value": 64091.35,
                         "full_accuracy_value": "64091...e18", "timestamp": <ms>}}

        The price is read from ``payload.value`` — a float already at full
        precision (``full_accuracy_value`` is the same number as a 1e18-scaled
        integer string and is intentionally not re-parsed, to avoid a scaling
        bug). ``price``/``p`` remain accepted as defensive fallbacks. Only
        configured symbols (``self._symbol_set``) with a strictly-positive finite
        price are accepted; everything else (acks, empty frames, off-map symbols)
        returns ``None`` — no fabrication.
        """
        if not isinstance(msg, dict):
            return None
        payload = msg.get("payload") if isinstance(msg.get("payload"), dict) else msg
        raw_symbol = (
            payload.get("symbol")
            or payload.get("asset")
            or payload.get("pair")
            or msg.get("symbol")
        )
        if not raw_symbol:
            return None
        symbol = normalize_symbol(str(raw_symbol))
        if symbol not in self._symbol_set:
            return None
        raw_price = (
            payload.get("value")
            if payload.get("value") is not None
            else payload.get("price")
            if payload.get("price") is not None
            else payload.get("p")
        )
        if raw_price is None or isinstance(raw_price, bool):
            return None
        try:
            price = float(raw_price)
        except (TypeError, ValueError):
            return None
        if price != price or price <= 0 or price in (float("inf"),):  # NaN/inf/<=0
            return None
        # Chainlink report time for the history ring — sanity-checked and
        # normalized to ms (a wrong-scale/garbage ts must never reach the ring,
        # whose prune anchor it would corrupt). Absence is tolerated (ts -> None;
        # the live cache still updates, only the candle-open lookup is unseeded).
        raw_ts = payload.get("timestamp")
        if raw_ts is None:
            raw_ts = msg.get("timestamp")
        ts_ms = _normalize_ts_ms(raw_ts)
        return symbol, price, ts_ms


def oracle_from_settings(
    *, connect_factory: Optional[ConnectFactory] = None
) -> PolymarketRTDSOracle:
    """Build the RTDS oracle from Settings.

    Honours the ``ORACLE_ENABLED`` feature flag (default OFF): the runtime
    entrypoint refuses to construct until the operator opts in. Tests construct
    :class:`PolymarketRTDSOracle` directly with a stub ``connect_factory``.
    """
    settings = get_settings()
    if not getattr(settings, "ORACLE_ENABLED", False):
        raise OracleDisabledError("ORACLE_ENABLED is OFF")
    return PolymarketRTDSOracle(
        ws_url=settings.ORACLE_RTDS_WS_URL,
        symbols=parse_symbols(settings.ORACLE_SYMBOLS),
        staleness_sec=settings.ORACLE_STALENESS_SEC,
        connect_factory=connect_factory,
        history_window_sec=getattr(
            settings, "ORACLE_HISTORY_WINDOW_SEC", _DEFAULT_HISTORY_WINDOW_SEC
        ),
    )
