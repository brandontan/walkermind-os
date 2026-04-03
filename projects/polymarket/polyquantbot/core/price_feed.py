"""core.price_feed — Real-time price feed integration for PolyQuantBot.

Connects the Polymarket WebSocket client to the PaperPositionManager so that
every orderbook or trade event triggers a mark-to-market price update on open
positions.  This drives live unrealized PnL recalculation and equity tracking.

Architecture::

    PolymarketWSClient
        │  WSEvent(type="orderbook"|"trade", market_id, timestamp, data)
        ▼
    PriceFeedHandler.on_event()
        │  Extracts mid-price from orderbook or last trade price
        ▼
    PaperPositionManager.update_price(market_id, price)
        │  Recalculates unrealized_pnl per position
        ▼
    WalletEngine.get_state() → updated equity exposed to Telegram

Design:
  - asyncio only — no threading.
  - Best-effort: a single failed update is logged but never crashes the feed.
  - Structured JSON logging on every price update.
  - Heartbeat: logs a summary every 60 s with total events processed.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Optional

import structlog

log = structlog.get_logger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

_HEARTBEAT_INTERVAL_S: float = 60.0  # summary log every 60 s


# ── Helpers ───────────────────────────────────────────────────────────────────


def _extract_mid_price(event_data: dict) -> Optional[float]:
    """Extract mid-price from an orderbook event data dict.

    Uses best-bid / best-ask average when both are available.
    Falls back to best bid or best ask alone.

    Args:
        event_data: ``WSEvent.data`` from an ``orderbook`` event.

    Returns:
        Mid-price float, or ``None`` if no valid price can be extracted.
    """
    bids: list = event_data.get("bids", [])
    asks: list = event_data.get("asks", [])

    best_bid: Optional[float] = None
    best_ask: Optional[float] = None

    if bids:
        try:
            best_bid = float(bids[0][0]) if isinstance(bids[0], (list, tuple)) else float(bids[0])
        except (IndexError, ValueError, TypeError):
            pass

    if asks:
        try:
            best_ask = float(asks[0][0]) if isinstance(asks[0], (list, tuple)) else float(asks[0])
        except (IndexError, ValueError, TypeError):
            pass

    if best_bid is not None and best_ask is not None:
        return round((best_bid + best_ask) / 2.0, 6)
    if best_bid is not None:
        return best_bid
    if best_ask is not None:
        return best_ask
    return None


def _extract_trade_price(event_data: dict) -> Optional[float]:
    """Extract last trade price from a trade event data dict.

    Args:
        event_data: ``WSEvent.data`` from a ``trade`` event.

    Returns:
        Trade price float, or ``None`` if not available.
    """
    try:
        price = float(event_data.get("price", 0.0))
        return price if price > 0.0 else None
    except (ValueError, TypeError):
        return None


# ── Handler ───────────────────────────────────────────────────────────────────


class PriceFeedHandler:
    """Routes WebSocket price events to the position manager.

    Args:
        positions:       :class:`~core.positions.PaperPositionManager` instance.
        wallet:          Optional :class:`~core.wallet_engine.WalletEngine` for
                         equity refresh after price update.
        on_price_update: Optional async callback ``(market_id, price)`` invoked
                         after every successful price update (e.g. to push
                         Telegram equity refresh).
    """

    def __init__(
        self,
        positions: Any,  # PaperPositionManager
        wallet: Optional[Any] = None,  # WalletEngine
        on_price_update: Optional[Callable[[str, float], Any]] = None,
    ) -> None:
        self._positions = positions
        self._wallet = wallet
        self._on_price_update = on_price_update
        self._events_processed: int = 0
        self._price_updates: int = 0
        self._started_at: float = time.monotonic()
        self._last_heartbeat: float = time.monotonic()

        log.info("price_feed_handler_initialized")

    # ── Public API ────────────────────────────────────────────────────────────

    async def on_event(self, event: Any) -> None:  # WSEvent
        """Process a single WebSocket price event.

        Extracts price from the event and calls
        ``PaperPositionManager.update_price()``.  Non-fatal: all exceptions
        are caught and logged.

        Args:
            event: :class:`~data.websocket.ws_client.WSEvent` instance.
        """
        self._events_processed += 1
        market_id: str = event.market_id
        price: Optional[float] = None

        try:
            if event.type == "orderbook":
                price = _extract_mid_price(event.data)
            elif event.type == "trade":
                price = _extract_trade_price(event.data)

            if price is None or price <= 0.0:
                return

            # Clamp to Polymarket valid range
            price = max(0.001, min(0.999, price))

            # Update position mark-to-market
            self._positions.update_price(market_id, price)
            self._price_updates += 1

            log.debug(
                "price_feed_update",
                market_id=market_id,
                price=price,
                event_type=event.type,
            )

            # Notify callback if registered
            if self._on_price_update is not None:
                try:
                    result = self._on_price_update(market_id, price)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as cb_exc:
                    log.warning(
                        "price_feed_callback_error",
                        market_id=market_id,
                        error=str(cb_exc),
                    )

        except Exception as exc:
            log.warning(
                "price_feed_event_error",
                market_id=market_id,
                event_type=getattr(event, "type", "unknown"),
                error=str(exc),
            )

        # ── Periodic heartbeat log ──────────────────────────────────────────
        elapsed = time.monotonic() - self._last_heartbeat
        if elapsed >= _HEARTBEAT_INTERVAL_S:
            log.info(
                "price_feed_heartbeat",
                events_processed=self._events_processed,
                price_updates=self._price_updates,
                uptime_s=round(time.monotonic() - self._started_at, 0),
            )
            self._last_heartbeat = time.monotonic()

    async def run(self, ws_client: Any) -> None:
        """Consume all events from a WebSocket client forever.

        Args:
            ws_client: :class:`~data.websocket.ws_client.PolymarketWSClient`
                       instance that has already been connected.
        """
        log.info("price_feed_run_started")
        async for event in ws_client.events():
            await self.on_event(event)
        log.info("price_feed_run_ended")

    def stats(self) -> dict:
        """Return a snapshot of feed statistics."""
        return {
            "events_processed": self._events_processed,
            "price_updates": self._price_updates,
            "uptime_s": round(time.monotonic() - self._started_at, 0),
        }
