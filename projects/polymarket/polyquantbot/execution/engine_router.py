"""execution.engine_router — Centralized dependency container for paper trading engines.

Provides a singleton :class:`EngineContainer` that holds all five core paper
trading engines.  Use :func:`get_engine_container` to obtain the shared
instance — duplicate calls always return the same object.

Engines:
    wallet     — :class:`~core.wallet_engine.WalletEngine`
    positions  — :class:`~core.positions.PaperPositionManager`
    ledger     — :class:`~core.ledger.TradeLedger`
    exposure   — :class:`~core.exposure.ExposureCalculator`
    paper_engine — :class:`~execution.paper_engine.PaperEngine`

Usage::

    from .execution.engine_router import get_engine_container

    container = get_engine_container()
    result = await container.paper_engine.execute_order(order_dict)

Design:
    - Singleton pattern: ``_container`` module-level guard prevents double init.
    - Structured JSON logging on init and every injection.
    - asyncio only — no threading.
    - All engines share the same wallet/positions/ledger instances (no duplication).
"""
from __future__ import annotations

from typing import Optional

import structlog

from ..core.wallet_engine import WalletEngine
from ..core.positions import PaperPositionManager
from ..core.ledger import TradeLedger
from ..core.exposure import ExposureCalculator
from .paper_engine import PaperEngine

log = structlog.get_logger(__name__)

# ── Singleton guard ───────────────────────────────────────────────────────────

_container: Optional["EngineContainer"] = None


# ── Container ─────────────────────────────────────────────────────────────────


class EngineContainer:
    """Holds all paper trading engine instances.

    Constructed exactly once via :func:`get_engine_container`.
    All five engines share their references — no duplication.

    Attributes:
        wallet:       Paper wallet (cash/locked/equity tracking).
        positions:    Position lifecycle manager.
        ledger:       Append-only trade ledger.
        exposure:     Exposure calculator.
        paper_engine: Full execution engine wired to the above.
    """

    def __init__(self) -> None:
        # ── Leaf engines (no dependencies) ────────────────────────────────────
        self.wallet: WalletEngine = WalletEngine()
        self.positions: PaperPositionManager = PaperPositionManager()
        # Alias for Telegram wallet handler compatibility
        self.paper_positions: PaperPositionManager = self.positions
        self.ledger: TradeLedger = TradeLedger()
        self.exposure: ExposureCalculator = ExposureCalculator()

        # ── Composite engine (depends on all three leaf engines) ───────────────
        self.paper_engine: PaperEngine = PaperEngine(
            wallet=self.wallet,
            positions=self.positions,
            ledger=self.ledger,
        )

        log.info(
            "engine_container_initialized",
            engines=["wallet", "positions", "ledger", "exposure", "paper_engine"],
        )

    # ── Startup persistence restore ───────────────────────────────────────────

    async def restore_from_db(self, db: object) -> None:
        """Restore all engine state from the database on startup.

        Calls restore hooks on wallet, positions, and ledger.  Non-fatal:
        each failure is logged and the engine starts with default state.

        Args:
            db: :class:`~infra.db.database.DatabaseClient` connected instance.
        """
        log.info("engine_container_restore_start")
        try:
            restored_wallet = await WalletEngine.restore_from_db(db)  # type: ignore[arg-type]
            self.wallet = restored_wallet
            self.paper_engine.bind_wallet(self.wallet)
            log.info("engine_container_wallet_restore_success")
        except Exception as exc:
            log.warning("engine_container_wallet_restore_error", error=str(exc))

        try:
            await self.positions.load_from_db(db)  # type: ignore[arg-type]
        except Exception as exc:
            log.warning("engine_container_positions_restore_error", error=str(exc))

        try:
            await self.ledger.load_from_db(db)  # type: ignore[arg-type]
            self.paper_engine.hydrate_processed_trade_ids(
                {entry.trade_id for entry in self.ledger.get_all()}
            )
            log.info("engine_container_dedup_hydration_success")
        except Exception as exc:
            log.warning("engine_container_ledger_restore_error", error=str(exc))

        log.info("engine_container_restore_complete")

    # ── Convenience ───────────────────────────────────────────────────────────

    def inject_into_handlers(self) -> None:
        """Inject all engines into their respective Telegram handler modules.

        Safe to call multiple times — each injection is idempotent at the
        module level (re-injection overwrites the previous reference).

        Handlers injected:
            - ``telegram.handlers.wallet``   ← WalletEngine
            - ``telegram.handlers.trade``    ← PaperEngine + PaperPositionManager
            - ``telegram.handlers.exposure`` ← ExposureCalculator + PaperPositionManager + WalletEngine
        """
        from ..telegram.handlers.wallet import set_paper_wallet_engine
        from ..telegram.handlers.trade import (
            set_paper_engine,
            set_position_manager as _set_trade_pm,
        )
        from ..telegram.handlers.exposure import (
            set_exposure_calculator,
            set_position_manager as _set_exp_pm,
            set_wallet_engine,
        )

        set_paper_wallet_engine(self.wallet)
        log.info("engine_injected", target="handlers.wallet", engine="WalletEngine")

        set_paper_engine(self.paper_engine)
        log.info("engine_injected", target="handlers.trade", engine="PaperEngine")

        _set_trade_pm(self.positions)
        log.info("engine_injected", target="handlers.trade", engine="PaperPositionManager")

        set_exposure_calculator(self.exposure)
        log.info("engine_injected", target="handlers.exposure", engine="ExposureCalculator")

        _set_exp_pm(self.positions)
        log.info("engine_injected", target="handlers.exposure", engine="PaperPositionManager")

        set_wallet_engine(self.wallet)
        log.info("engine_injected", target="handlers.exposure", engine="WalletEngine")


# ── Factory ───────────────────────────────────────────────────────────────────


def get_engine_container() -> EngineContainer:
    """Return the singleton :class:`EngineContainer`, creating it on first call.

    Thread-safety: This function is synchronous and runs in the asyncio event
    loop's single thread — there are no concurrent Python threads, so no lock
    is required.  The check-and-set of ``_container`` is atomic within a single
    asyncio execution context.  Do NOT call from a ``ThreadPoolExecutor`` or any
    multi-threaded context.

    Warning: Call this function only after the asyncio event loop is running
    (i.e., from within a coroutine or an already-started async context).
    Do NOT call at module import time or during static initialisation, as the
    engines it creates may depend on an active event loop.

    Returns:
        The shared :class:`EngineContainer` instance.
    """
    global _container  # noqa: PLW0603
    if _container is None:
        log.info("engine_container_creating_singleton")
        _container = EngineContainer()
    else:
        log.debug("engine_container_singleton_reused")
    return _container
