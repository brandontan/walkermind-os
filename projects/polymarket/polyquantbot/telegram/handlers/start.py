"""telegram.handlers.start — Premium /start boot screen handler for PolyQuantBot.

Produces an institutional-grade terminal boot screen showing:
  - System state (RUNNING / PAUSED / HALTED)
  - Trading mode (PAPER / LIVE)
  - Wallet snapshot (cash, equity)
  - Active strategies
  - PnL summary
  - Pipeline metrics (latency, markets scanned)

Dependencies are injected at bot startup.

Return type for all handlers: tuple[str, list]  (text, InlineKeyboard)
"""
from __future__ import annotations

import asyncio
from typing import Optional, TYPE_CHECKING

import structlog

from ..ui.components import render_start_screen, render_status_bar
from ..ui.keyboard import build_main_menu

if TYPE_CHECKING:
    from ...core.system_state import SystemStateManager
    from ...config.runtime_config import ConfigManager
    from ...strategy.strategy_manager import StrategyStateManager
    from ...core.wallet_engine import WalletEngine
    from ...core.positions import PaperPositionManager
    from ...core.portfolio.pnl import PnLTracker

log = structlog.get_logger(__name__)

_FETCH_TIMEOUT_S: float = 2.0

# ── Injected dependencies ─────────────────────────────────────────────────────

_state_manager: Optional["SystemStateManager"] = None
_config_manager: Optional["ConfigManager"] = None
_strategy_state: Optional["StrategyStateManager"] = None
_wallet_engine: Optional["WalletEngine"] = None
_position_manager: Optional["PaperPositionManager"] = None
_pnl_tracker: Optional["PnLTracker"] = None
_mode: str = "PAPER"


def set_state_manager(sm: "SystemStateManager") -> None:
    """Inject SystemStateManager at bot startup."""
    global _state_manager  # noqa: PLW0603
    _state_manager = sm
    log.info("start_handler_state_manager_injected")


def set_config_manager(cm: "ConfigManager") -> None:
    """Inject ConfigManager at bot startup."""
    global _config_manager  # noqa: PLW0603
    _config_manager = cm
    log.info("start_handler_config_manager_injected")


def set_strategy_state(ss: "StrategyStateManager") -> None:
    """Inject StrategyStateManager at bot startup."""
    global _strategy_state  # noqa: PLW0603
    _strategy_state = ss
    log.info("start_handler_strategy_state_injected")


def set_wallet_engine(engine: "WalletEngine") -> None:
    """Inject WalletEngine at bot startup."""
    global _wallet_engine  # noqa: PLW0603
    _wallet_engine = engine
    log.info("start_handler_wallet_engine_injected")


def set_position_manager(pm: "PaperPositionManager") -> None:
    """Inject PaperPositionManager at bot startup."""
    global _position_manager  # noqa: PLW0603
    _position_manager = pm
    log.info("start_handler_position_manager_injected")


def set_pnl_tracker(tracker: "PnLTracker") -> None:
    """Inject PnLTracker at bot startup."""
    global _pnl_tracker  # noqa: PLW0603
    _pnl_tracker = tracker
    log.info("start_handler_pnl_tracker_injected")


def set_mode(mode: str) -> None:
    """Update trading mode string."""
    global _mode  # noqa: PLW0603
    _mode = mode
    log.info("start_handler_mode_updated", mode=mode)


# ── Handler ───────────────────────────────────────────────────────────────────


async def handle_start() -> tuple[str, list]:
    """Return the premium boot screen with full system snapshot.

    Assembles:
      1. System state from StateManager
      2. Wallet snapshot from WalletEngine
      3. Active strategy list from StrategyStateManager
      4. PnL summary from PnLTracker

    All sources are fault-tolerant: missing/unavailable services
    produce safe zero-value fallbacks, never a crash.

    Returns:
        ``(screen_text, keyboard)`` tuple.
    """
    # ── Collect system state ────────────────────────────────────────────────
    system_state = "RUNNING"
    if _state_manager is not None:
        try:
            snap = _state_manager.snapshot()
            system_state = snap.get("state", "RUNNING")
        except Exception as exc:
            log.warning("start_handler_state_fetch_error", error=str(exc))

    # ── Collect wallet data ─────────────────────────────────────────────────
    wallet_cash: float = 0.0
    wallet_equity: float = 0.0
    open_positions: int = 0

    if _wallet_engine is not None:
        try:
            ws = _wallet_engine.get_state()
            wallet_cash = ws.cash
            wallet_equity = ws.equity
        except Exception as exc:
            log.warning("start_handler_wallet_fetch_error", error=str(exc))

    if _position_manager is not None:
        try:
            positions = _position_manager.get_all_open()
            open_positions = len(positions)
        except Exception as exc:
            log.warning("start_handler_positions_fetch_error", error=str(exc))

    # ── Collect PnL ─────────────────────────────────────────────────────────
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0

    if _pnl_tracker is not None:
        try:
            summary = _pnl_tracker.summary()
            realized_pnl = summary.get("total_realized", 0.0)
            unrealized_pnl = summary.get("total_unrealized", 0.0)
        except Exception as exc:
            log.warning("start_handler_pnl_fetch_error", error=str(exc))

    # Also check positions for unrealized if tracker didn't provide it
    if unrealized_pnl == 0.0 and _position_manager is not None:
        try:
            positions = _position_manager.get_all_open()
            unrealized_pnl = sum(p.unrealized_pnl for p in positions)
        except Exception:
            pass

    # ── Collect strategies ──────────────────────────────────────────────────
    active_strategies: list[str] = []

    if _strategy_state is not None:
        try:
            active_strategies = _strategy_state.get_active()
        except Exception as exc:
            log.warning("start_handler_strategy_fetch_error", error=str(exc))

    # ── Render ──────────────────────────────────────────────────────────────
    text = render_start_screen(
        system_state=system_state,
        mode=_mode,
        wallet_cash=wallet_cash,
        wallet_equity=wallet_equity,
        open_positions=open_positions,
        active_strategies=active_strategies,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
    )

    log.info(
        "start_handler_displayed",
        state=system_state,
        mode=_mode,
        cash=wallet_cash,
        equity=wallet_equity,
        open_positions=open_positions,
        active_strategies=active_strategies,
    )

    return text, build_main_menu()
