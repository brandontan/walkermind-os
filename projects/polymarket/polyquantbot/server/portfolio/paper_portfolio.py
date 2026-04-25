"""Paper portfolio engine — wires PaperEngine to the public beta worker pipeline.

Replaces the 21-line stub with proper PaperEngine integration including:
- Fractional Kelly (a=0.25) position sizing
- Real wallet / position / ledger / PnL tracking via core engines
- STATE synchronisation after every execution (incl. drawdown + net PnL)
- Per-signal edge tracking so STATE.positions retains edge values
- Peak-equity drawdown calculation for live risk gate enforcement
- Operator reset path via module-level active-portfolio singleton

Constants (per AGENTS.md hard rules):
    KELLY_FRACTION   = 0.25   (fractional only — a=1.0 FORBIDDEN)
    MAX_POSITION_PCT = 0.10   (max 10 % of equity)
    MIN_POSITION_USD = 10.0   (floor to avoid dust trades)
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Optional

import structlog

from projects.polymarket.polyquantbot.core.wallet_engine import WalletEngine
from projects.polymarket.polyquantbot.core.positions import PaperPositionManager
from projects.polymarket.polyquantbot.core.ledger import TradeLedger
from projects.polymarket.polyquantbot.core.portfolio.pnl import PnLTracker
from projects.polymarket.polyquantbot.execution.paper_engine import PaperEngine
from projects.polymarket.polyquantbot.server.core.public_beta_state import (
    PaperPosition as StatePaperPosition,
    PublicBetaState,
)
from projects.polymarket.polyquantbot.server.integrations.falcon_gateway import CandidateSignal

log = structlog.get_logger(__name__)

# ── Risk constants (LOCKED per AGENTS.md) ────────────────────────────────────
_KELLY_FRACTION: float = 0.25       # fractional Kelly — never 1.0
_MAX_POSITION_PCT: float = 0.10     # max 10 % of equity per position
_MIN_POSITION_USD: float = 10.0     # minimum trade size in USD

# ── Module-level active-portfolio singleton ───────────────────────────────────
# Registered by run_worker_loop() so operator /reset can reach the live instance.
_ACTIVE_PORTFOLIO: Optional["PaperPortfolio"] = None


def get_active_portfolio() -> Optional["PaperPortfolio"]:
    """Return the currently active PaperPortfolio registered by the worker."""
    return _ACTIVE_PORTFOLIO


def _register_portfolio(portfolio: "PaperPortfolio") -> None:
    """Register the live portfolio instance (called from run_worker_loop)."""
    global _ACTIVE_PORTFOLIO  # noqa: PLW0603
    _ACTIVE_PORTFOLIO = portfolio
    log.info("paper_portfolio_registered", engine_id=id(portfolio._engine))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_paper_engine() -> PaperEngine:
    """Construct and wire the full core engine stack."""
    wallet = WalletEngine()
    positions = PaperPositionManager()
    ledger = TradeLedger()
    pnl_tracker = PnLTracker()
    return PaperEngine(
        wallet=wallet,
        positions=positions,
        ledger=ledger,
        pnl_tracker=pnl_tracker,
    )


def _kelly_size(edge: float, price: float, equity: float) -> float:
    """Return fractional Kelly position size in USD.

    Kelly fraction = edge / price (binary prediction market approximation).
    Fractional Kelly (a=0.25) keeps exposure bounded well within max drawdown limits.
    """
    kelly_f = edge / max(price, 0.01)
    size = equity * _KELLY_FRACTION * kelly_f
    size = min(size, equity * _MAX_POSITION_PCT)
    return max(round(size, 2), _MIN_POSITION_USD)


# ── Portfolio ─────────────────────────────────────────────────────────────────


class PaperPortfolio:
    """Wiring layer between CandidateSignal and the real PaperEngine.

    Owns the full core engine stack (wallet, positions, ledger, pnl_tracker).
    Provides async open/close/reset and STATE synchronisation.
    """

    def __init__(self, paper_engine: Optional[PaperEngine] = None) -> None:
        self._engine: PaperEngine = paper_engine if paper_engine is not None else _build_paper_engine()
        self._lock = asyncio.Lock()
        # Peak equity for drawdown calculation — starts at initial wallet equity.
        self._peak_equity: float = self._engine.get_wallet_state().equity
        # Signal edge map — persists edge per condition_id so _sync_state can restore it.
        self._signal_edges: dict[str, float] = {}
        log.info("paper_portfolio_initialized", engine_id=id(self._engine))

    # ── STATE sync ────────────────────────────────────────────────────────────

    def _sync_state(self, state: PublicBetaState) -> None:
        """Sync PublicBetaState from real engine components.

        Updates: wallet fields, positions (with edge), exposure, realized PnL,
        net PnL (realized + unrealized), and drawdown.
        """
        ws = self._engine.get_wallet_state()
        state.wallet_cash = ws.cash
        state.wallet_locked = ws.locked
        state.wallet_equity = ws.equity

        # Peak equity tracking for drawdown
        if ws.equity > self._peak_equity:
            self._peak_equity = ws.equity
        drawdown = (self._peak_equity - ws.equity) / max(self._peak_equity, 1.0)
        state.drawdown = round(max(drawdown, 0.0), 6)

        open_positions = self._engine.get_open_positions()
        state.positions = [
            StatePaperPosition(
                condition_id=p.market_id,
                side=p.side,
                size=p.size,
                entry_price=p.entry_price,
                edge=self._signal_edges.get(p.market_id, 0.0),
                unrealized_pnl=p.unrealized_pnl,
            )
            for p in open_positions
        ]

        state.exposure = ws.locked / max(ws.equity, 1.0) if ws.equity > 0 else 0.0
        realized = self._engine.get_realized_pnl()
        unrealized = sum(p.unrealized_pnl for p in open_positions)
        state.realized_pnl = round(realized, 4)
        state.pnl = round(realized + unrealized, 4)   # net PnL

    # ── Public interface ──────────────────────────────────────────────────────

    async def open_position(
        self,
        signal: CandidateSignal,
        state: PublicBetaState,
    ) -> StatePaperPosition:
        """Convert signal → Kelly-sized order → PaperEngine → sync STATE.

        Args:
            signal: CandidateSignal from FalconGateway.
            state:  Live PublicBetaState to synchronise after execution.

        Returns:
            StatePaperPosition representing the opened/accumulated position.
        """
        async with self._lock:
            ws = self._engine.get_wallet_state()
            equity = max(ws.equity, 1.0)
            size_usd = _kelly_size(signal.edge, signal.price, equity)

            # Persist edge so _sync_state can include it in STATE.positions
            self._signal_edges[signal.condition_id] = signal.edge

            trade_id = f"sig-{signal.signal_id[:16]}-{uuid.uuid4().hex[:8]}"
            order = {
                "trade_id": trade_id,
                "market_id": signal.condition_id,
                "side": signal.side.upper(),
                "price": signal.price,
                "size": size_usd,
            }

            result = await self._engine.execute_order(order)
            state.processed_signals.add(signal.signal_id)
            self._sync_state(state)

            log.info(
                "paper_portfolio_position_opened",
                signal_id=signal.signal_id,
                condition_id=signal.condition_id,
                trade_id=trade_id,
                fill_status=result.status,
                filled_size=result.filled_size,
                fill_price=result.fill_price,
            )

            # Return state-facing position (most recent open for this market)
            open_positions = self._engine.get_open_positions()
            matched = next(
                (p for p in open_positions if p.market_id == signal.condition_id),
                None,
            )
            if matched is not None:
                return StatePaperPosition(
                    condition_id=matched.market_id,
                    side=matched.side,
                    size=matched.size,
                    entry_price=matched.entry_price,
                    edge=signal.edge,
                    unrealized_pnl=matched.unrealized_pnl,
                )

            # Fallback (e.g. REJECTED) — return signal data
            return StatePaperPosition(
                condition_id=signal.condition_id,
                side=signal.side,
                size=result.filled_size,
                entry_price=result.fill_price,
                edge=signal.edge,
                unrealized_pnl=0.0,
            )

    async def close_position(
        self,
        market_id: str,
        close_price: float,
        state: PublicBetaState,
    ) -> None:
        """Close a position and sync STATE."""
        async with self._lock:
            await self._engine.close_order(
                market_id=market_id,
                close_price=close_price,
            )
            self._sync_state(state)
            log.info(
                "paper_portfolio_position_closed",
                market_id=market_id,
                close_price=close_price,
            )

    async def reset(self, state: PublicBetaState) -> None:
        """Reset paper account — rebuilds engine stack and clears STATE.

        Operator-only path. Resets wallet to initial balance, clears
        all positions, ledger, PnL tracker, and processed signals.
        """
        async with self._lock:
            self._engine = _build_paper_engine()
            self._peak_equity = self._engine.get_wallet_state().equity
            self._signal_edges = {}
            state.positions = []
            state.processed_signals = set()
            state.pnl = 0.0
            state.realized_pnl = 0.0
            state.drawdown = 0.0
            state.exposure = 0.0
            state.last_risk_reason = ""
            self._sync_state(state)
            log.info("paper_portfolio_reset", equity=state.wallet_equity)

    def get_paper_engine(self) -> PaperEngine:
        """Return the underlying PaperEngine for dependency injection."""
        return self._engine

    def get_position_manager(self) -> PaperPositionManager:
        """Return the PaperPositionManager for Telegram handler injection."""
        return self._engine.position_manager

    def get_pnl_tracker(self) -> object:
        """Return the PnLTracker for Telegram handler injection."""
        return self._engine.pnl_tracker

    def sync_state(self, state: PublicBetaState) -> None:
        """Force a STATE sync — useful after price updates."""
        self._sync_state(state)
