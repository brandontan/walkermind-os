"""Wallet handler — returns (text, keyboard) for wallet-related screens.

Full premium terminal UI using ui/components.py renderers.

Features:
  - Paper wallet: cash, locked, equity, buying power, exposure, PnL
  - Live wallet: on-chain balance via WalletService
  - Withdraw simulation (paper) with hard reject on insufficient funds
  - Status bar on every screen
  - DB-backed state (no stale cache mismatch)

WalletService / WalletEngine are injected at bot startup.

Return type: tuple[str, InlineKeyboard]
"""
from __future__ import annotations

import asyncio
from typing import Optional, TYPE_CHECKING

import structlog

from ..ui.keyboard import build_wallet_menu, build_paper_wallet_menu
from ..ui.components import render_wallet_card, render_status_bar
from ..ui.screens import (
    wallet_withdraw_screen,
    wallet_withdraw_result_screen,
)

if TYPE_CHECKING:
    from ...core.wallet.service import WalletService
    from ...core.wallet_engine import WalletEngine
    from ...core.positions import PaperPositionManager
    from ...core.portfolio.pnl import PnLTracker
    from ...core.system_state import SystemStateManager

log = structlog.get_logger(__name__)

_BALANCE_FETCH_TIMEOUT_S: float = 2.0

# ── Injected dependencies ─────────────────────────────────────────────────────

_wallet_service: Optional["WalletService"] = None
_cached_balance: Optional[float] = None
_cached_address: Optional[str] = None

_paper_wallet_engine: Optional["WalletEngine"] = None
_position_manager: Optional["PaperPositionManager"] = None
_pnl_tracker: Optional["PnLTracker"] = None
_system_state: Optional["SystemStateManager"] = None
_mode: str = "PAPER"


def set_paper_wallet_engine(engine: "WalletEngine") -> None:
    """Inject the WalletEngine (paper trading) into the wallet handler."""
    global _paper_wallet_engine  # noqa: PLW0603
    _paper_wallet_engine = engine
    log.info("wallet_handler_paper_engine_injected")


def set_wallet_service(service: "WalletService") -> None:
    """Inject the WalletService into the wallet handler."""
    global _wallet_service  # noqa: PLW0603
    _wallet_service = service
    log.info("wallet_handler_service_injected")


def set_position_manager(pm: "PaperPositionManager") -> None:
    """Inject PaperPositionManager at bot startup."""
    global _position_manager  # noqa: PLW0603
    _position_manager = pm
    log.info("wallet_handler_position_manager_injected")


def set_pnl_tracker(tracker: "PnLTracker") -> None:
    """Inject PnLTracker at bot startup."""
    global _pnl_tracker  # noqa: PLW0603
    _pnl_tracker = tracker
    log.info("wallet_handler_pnl_tracker_injected")


def set_system_state(sm: "SystemStateManager") -> None:
    """Inject SystemStateManager at bot startup."""
    global _system_state  # noqa: PLW0603
    _system_state = sm
    log.info("wallet_handler_system_state_injected")


def set_mode(mode: str) -> None:
    """Update trading mode string."""
    global _mode  # noqa: PLW0603
    _mode = mode


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_status_bar() -> str:
    sys_state = "RUNNING"
    if _system_state is not None:
        try:
            snap = _system_state.snapshot()
            sys_state = snap.get("state", "RUNNING")
        except Exception:
            pass
    return render_status_bar(state=sys_state, mode=_mode)


def _collect_paper_metrics() -> tuple[float, float, float, float, float, int]:
    """Return (cash, locked, equity, realized_pnl, unrealized_pnl, open_count)."""
    cash = locked = equity = realized_pnl = unrealized_pnl = 0.0
    open_count = 0

    if _paper_wallet_engine is not None:
        try:
            ws = _paper_wallet_engine.get_state()
            cash = ws.cash
            locked = ws.locked
            equity = ws.equity
        except Exception as exc:
            log.warning("wallet_paper_state_error", error=str(exc))

    if _position_manager is not None:
        try:
            positions = _position_manager.get_all_open()
            open_count = len(positions)
            unrealized_pnl = sum(p.unrealized_pnl for p in positions)
        except Exception as exc:
            log.warning("wallet_positions_error", error=str(exc))

    if _pnl_tracker is not None:
        try:
            summary = _pnl_tracker.summary()
            realized_pnl = summary.get("total_realized", 0.0)
        except Exception as exc:
            log.warning("wallet_pnl_tracker_error", error=str(exc))

    return cash, locked, equity, realized_pnl, unrealized_pnl, open_count


# ── Main wallet screens ───────────────────────────────────────────────────────

async def handle_wallet(mode: str, user_id: Optional[int] = None) -> tuple[str, list]:
    """Return wallet overview screen.

    In PAPER mode: uses WalletEngine (cash/locked/equity) + premium card.
    In LIVE mode: fetches on-chain balance via WalletService.
    """
    global _cached_balance, _cached_address  # noqa: PLW0603

    # Paper mode — use WalletEngine
    if _mode == "PAPER" and _paper_wallet_engine is not None:
        return await handle_paper_wallet(mode=mode)

    # Live mode — use WalletService
    if _wallet_service is None or user_id is None:
        status_bar = _get_status_bar()
        text = (
            f"{status_bar}\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "💼 *WALLET*\n\n"
            "_Wallet service not available._"
        )
        return text, build_wallet_menu()

    try:
        wallet = await asyncio.wait_for(
            _wallet_service.get_wallet(user_id), timeout=_BALANCE_FETCH_TIMEOUT_S
        )
        if wallet is None:
            wallet = await asyncio.wait_for(
                _wallet_service.create_wallet(user_id), timeout=_BALANCE_FETCH_TIMEOUT_S
            )
        balance = await asyncio.wait_for(
            _wallet_service.get_balance(user_id), timeout=_BALANCE_FETCH_TIMEOUT_S
        )
        if wallet is not None:
            _cached_address = wallet.address
        if balance is not None:
            _cached_balance = balance

        address = wallet.address if wallet else _cached_address
        status_bar = _get_status_bar()
        text = (
            f"{status_bar}\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💼 *WALLET* — LIVE MODE\n\n"
            f"🔑 Address: `{address or 'N/A'}`\n"
            f"💵 Balance: `${balance or 0.0:,.4f} USDC`"
        )
        return text, build_wallet_menu()

    except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
        if isinstance(exc, asyncio.CancelledError):
            raise
        log.warning("handle_wallet_timeout", user_id=user_id)
    except Exception as exc:
        log.error("handle_wallet_error", user_id=user_id, error=str(exc))

    status_bar = _get_status_bar()
    text = (
        f"{status_bar}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💼 *WALLET* — LIVE MODE\n\n"
        f"🔑 Address: `{_cached_address or 'N/A'}`\n"
        f"⚠️ Using cached balance: `${_cached_balance or 0.0:,.4f} USDC`"
    )
    return text, build_wallet_menu()


async def handle_paper_wallet(mode: str = "default") -> tuple[str, list]:
    """Return full paper wallet terminal card.

    Shows: cash, locked, equity, buying power, exposure, realized PnL,
    unrealized PnL, open position count. Uses WalletEngine DB state.
    """
    if _paper_wallet_engine is None:
        log.warning("handle_paper_wallet_no_engine")
        status_bar = _get_status_bar()
        return (
            f"{status_bar}\n⚠️ *Paper Wallet*\n\n_Engine not available._",
            build_wallet_menu(),
        )

    cash, locked, equity, realized_pnl, unrealized_pnl, open_count = _collect_paper_metrics()

    status_bar = _get_status_bar()
    text = render_wallet_card(
        cash=cash,
        locked=locked,
        equity=equity,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
        open_positions=open_count,
        mode="PAPER",
        status_bar=status_bar,
    )

    log.info(
        "handle_paper_wallet_displayed",
        cash=cash,
        locked=locked,
        equity=equity,
        unrealized_pnl=unrealized_pnl,
        open_positions=open_count,
    )
    return text, build_paper_wallet_menu()


async def handle_wallet_balance(user_id: Optional[int] = None) -> tuple[str, list]:
    """Return balance detail screen.

    In PAPER mode: shows full wallet card from WalletEngine (DB state).
    In LIVE mode: fetches on-chain balance with 3× retry.
    """
    global _cached_balance, _cached_address  # noqa: PLW0603

    if _mode == "PAPER" and _paper_wallet_engine is not None:
        return await handle_paper_wallet()

    if _wallet_service is None or user_id is None:
        status_bar = _get_status_bar()
        return (
            f"{status_bar}\n💵 *BALANCE*\n\n_Wallet service not available._",
            build_wallet_menu(),
        )

    for attempt in range(1, 4):
        try:
            wallet = await asyncio.wait_for(
                _wallet_service.get_wallet(user_id), timeout=_BALANCE_FETCH_TIMEOUT_S
            )
            balance = await asyncio.wait_for(
                _wallet_service.get_balance(user_id), timeout=_BALANCE_FETCH_TIMEOUT_S
            )
            address = wallet.address if wallet else None
            if address is not None:
                _cached_address = address
            if balance is not None:
                _cached_balance = balance
            log.info("wallet_fetch", status="success", user_id=user_id, balance=balance, attempt=attempt)

            status_bar = _get_status_bar()
            text = (
                f"{status_bar}\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "💵 *BALANCE DETAIL*\n\n"
                f"🔑 Address: `{address or 'N/A'}`\n"
                f"💵 Available: `${balance or 0.0:,.4f}`\n"
                f"🔒 Locked:    `$0.0000` _(tracked in paper wallet)_\n"
                f"📊 Total:     `${balance or 0.0:,.4f}`"
            )
            return text, build_wallet_menu()
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError:
            log.warning("wallet_fetch", status="timeout", user_id=user_id, attempt=attempt)
        except Exception as exc:
            log.warning("wallet_fetch", status="error", user_id=user_id, attempt=attempt, error=str(exc))
        if attempt < 3:
            await asyncio.sleep(0.5 * attempt)

    log.error("wallet_fetch_all_retries_exhausted", user_id=user_id)
    if _cached_balance is not None:
        status_bar = _get_status_bar()
        return (
            f"{status_bar}\n💵 *BALANCE*\n\n⚠️ Cached: `${_cached_balance:,.4f} USDC`",
            build_wallet_menu(),
        )
    return "❌ Failed to fetch wallet balance.", build_wallet_menu()


async def handle_wallet_exposure(user_id: Optional[int] = None) -> tuple[str, list]:
    """Return exposure screen — delegates to exposure handler."""
    from .exposure import handle_exposure  # noqa: PLC0415
    return await handle_exposure()


async def handle_wallet_withdraw(user_id: Optional[int] = None) -> tuple[str, list]:
    """Return withdraw initiation screen with available balance."""
    global _cached_balance, _cached_address  # noqa: PLW0603

    status_bar = _get_status_bar()

    if _mode == "PAPER" and _paper_wallet_engine is not None:
        try:
            ws = _paper_wallet_engine.get_state()
            text = (
                f"{status_bar}\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "💸 *WITHDRAW — PAPER SIMULATION*\n\n"
                f"💵 Available Cash: `${ws.cash:,.4f}`\n"
                f"🔒 Locked (positions): `${ws.locked:,.4f}`\n\n"
                "_Use `/withdraw <amount>` to simulate deduction._\n"
                "_(No real funds will move — paper mode only)_"
            )
        except Exception as exc:
            log.error("wallet_withdraw_paper_state_error", error=str(exc))
            text = f"{status_bar}\n❌ *Error fetching paper wallet state*"
        return text, build_paper_wallet_menu()

    # Live mode
    if _wallet_service is None or user_id is None:
        return wallet_withdraw_screen(address=_cached_address, balance=_cached_balance), build_wallet_menu()

    try:
        wallet = await asyncio.wait_for(
            _wallet_service.get_wallet(user_id), timeout=_BALANCE_FETCH_TIMEOUT_S
        )
        balance = await asyncio.wait_for(
            _wallet_service.get_balance(user_id), timeout=_BALANCE_FETCH_TIMEOUT_S
        )
        address = wallet.address if wallet else None
        if address is not None:
            _cached_address = address
        if balance is not None:
            _cached_balance = balance
        return wallet_withdraw_screen(address=address, balance=balance), build_wallet_menu()
    except asyncio.TimeoutError:
        log.warning("handle_wallet_withdraw_timeout", user_id=user_id)
        return wallet_withdraw_screen(address=_cached_address, balance=_cached_balance), build_wallet_menu()
    except Exception as exc:
        log.error("handle_wallet_withdraw_error", user_id=user_id, error=str(exc))
        return wallet_withdraw_screen(address=_cached_address, balance=_cached_balance), build_wallet_menu()


async def handle_paper_withdraw_command(amount: float) -> tuple[str, list]:
    """Simulate a paper wallet withdrawal — reduce available cash.

    Args:
        amount: Amount in USD to deduct from paper cash balance.

    Returns:
        ``(screen_text, keyboard)`` tuple.
    """
    from ...core.wallet_engine import InsufficientFundsError  # noqa: PLC0415

    status_bar = _get_status_bar()

    if _paper_wallet_engine is None:
        return (
            f"{status_bar}\n⚠️ Paper wallet engine not available.",
            build_paper_wallet_menu(),
        )

    if amount <= 0:
        return (
            f"{status_bar}\n❌ *Invalid amount.* Must be > 0.",
            build_paper_wallet_menu(),
        )

    try:
        state_before = _paper_wallet_engine.get_state()
        if state_before.cash < amount:
            return (
                f"{status_bar}\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "❌ *Withdraw Rejected*\n\n"
                f"Requested: `${amount:,.4f}`\n"
                f"Available: `${state_before.cash:,.4f}`\n\n"
                "_Insufficient funds. Cannot withdraw._",
                build_paper_wallet_menu(),
            )

        new_state = await _paper_wallet_engine.withdraw(
            amount=amount,
            reference="telegram_withdraw",
        )
        log.info(
            "paper_withdraw_executed",
            amount=amount,
            cash_after=new_state.cash,
            equity_after=new_state.equity,
        )
        return (
            f"{status_bar}\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "✅ *Paper Withdrawal Simulated*\n\n"
            f"💸 Amount:    `-${amount:,.4f}`\n"
            f"💵 Cash Now:  `${new_state.cash:,.4f}`\n"
            f"📊 Equity:    `${new_state.equity:,.4f}`\n\n"
            "_No real funds moved — paper simulation only._",
            build_paper_wallet_menu(),
        )
    except InsufficientFundsError as exc:
        log.warning("paper_withdraw_insufficient_funds", amount=amount, error=str(exc))
        return (
            f"{status_bar}\n❌ *Withdraw failed:* `{exc}`",
            build_paper_wallet_menu(),
        )
    except Exception as exc:
        log.error("paper_withdraw_unexpected_error", amount=amount, error=str(exc))
        return (
            f"{status_bar}\n❌ *Unexpected error during withdraw.*",
            build_paper_wallet_menu(),
        )


async def handle_withdraw_command(
    user_id: Optional[int],
    to_address: str,
    amount_usdc: float,
) -> tuple[str, list]:
    """Execute a USDC withdrawal.

    Priority:
    1. If WalletService is available → live blockchain withdrawal
    2. Elif paper_wallet_engine available → paper simulation
    3. Else → return withdraw screen stub

    Args:
        user_id:      Telegram user ID.
        to_address:   Destination 0x address.
        amount_usdc:  Amount in USDC.
    """
    # ── LIVE: WalletService takes priority when injected ─────────────────────
    if _wallet_service is not None and user_id is not None:
        try:
            result = await _wallet_service.withdraw(
                user_id=user_id,
                to_address=to_address,
                amount_usdc=amount_usdc,
            )
            log.info(
                "withdraw_command_success",
                user_id=user_id,
                status=result.get("status"),
                tx_hash=result.get("tx_hash"),
            )
            return wallet_withdraw_result_screen(result), build_wallet_menu()
        except (ValueError, RuntimeError) as exc:
            log.warning("withdraw_command_error", user_id=user_id, error=str(exc))
            return (
                "❌ *Withdraw Failed*\n\n"
                f"`{exc}`\n\n"
                "_Check address format and available balance._"
            ), build_wallet_menu()
        except Exception as exc:
            log.error("withdraw_command_unexpected_error", user_id=user_id, error=str(exc))
            return wallet_withdraw_screen(), build_wallet_menu()

    # ── PAPER: simulate deduction from paper cash ─────────────────────────────
    if _paper_wallet_engine is not None:
        return await handle_paper_withdraw_command(amount=amount_usdc)

    return wallet_withdraw_screen(), build_wallet_menu()

