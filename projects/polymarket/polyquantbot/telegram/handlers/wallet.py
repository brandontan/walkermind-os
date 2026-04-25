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
from ..ui.components import render_wallet_card, render_status_bar, render_kv_line, render_insight, SEP
from ..ui.screens import (
    wallet_withdraw_screen,
    wallet_withdraw_result_screen,
)
from .portfolio_service import get_portfolio_service

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

# P4: lifecycle service injection
_wallet_lifecycle_service: Optional[object] = None  # WalletLifecycleService


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


def set_wallet_lifecycle_service(svc: object) -> None:
    """Inject WalletLifecycleService for P4 lifecycle status display."""
    global _wallet_lifecycle_service  # noqa: PLW0603
    _wallet_lifecycle_service = svc
    log.info("wallet_handler_lifecycle_service_injected")


# ── Section 29: Wallet lifecycle status display (P4) ─────────────────────────

async def handle_wallet_lifecycle_status(
    tenant_id: str,
    user_id: str,
) -> tuple[str, list]:
    """Return wallet lifecycle status summary for Telegram display.

    Shows all wallets for the user with their current FSM status.
    Keeps copy safe — no addresses leaked beyond first/last 4 chars.
    """
    if _wallet_lifecycle_service is None:
        return (
            "⚙️ Wallet lifecycle service not available.",
            [],
        )
    try:
        wallets = await _wallet_lifecycle_service.list_wallets(  # type: ignore[union-attr]
            tenant_id=tenant_id, user_id=user_id
        )
        if not wallets:
            return (
                "No wallets registered.\n\nUse /link to connect a wallet.",
                [],
            )
        lines = ["Wallet Status\n"]
        for w in wallets:
            addr = w.address
            safe_addr = f"{addr[:6]}...{addr[-4:]}" if len(addr) > 10 else addr
            status_icon = {
                "unlinked": "○",
                "linked": "◎",
                "active": "●",
                "deactivated": "◌",
                "blocked": "✕",
            }.get(w.status.value, "?")
            lines.append(f"{status_icon} {safe_addr}  [{w.status.value}]")
        return ("\n".join(lines), [])
    except Exception as exc:
        log.error("wallet_lifecycle_status_error", error=str(exc))
        return ("Unable to load wallet status.", [])


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


def _collect_paper_metrics() -> Optional[tuple[float, float, float, float, float, int]]:
    """Return (cash, locked, equity, realized_pnl, unrealized_pnl, open_count)."""
    portfolio = get_portfolio_service().get_state()
    if portfolio is None:
        return None

    cash = portfolio.cash
    equity = portfolio.equity
    realized_pnl = portfolio.pnl
    unrealized_pnl = sum(pos.unrealized_pnl for pos in portfolio.positions)
    open_count = len(portfolio.positions)
    locked = max(equity - cash, 0.0)
    return cash, locked, equity, realized_pnl, unrealized_pnl, open_count


def _live_wallet_screen(
    status_bar: str,
    address: Optional[str],
    balance: Optional[float],
    stale: bool = False,
) -> str:
    """Render live wallet screen text for LIVE mode (STYLE B).

    Args:
        status_bar: Pre-rendered status bar block.
        address:    Wallet address or None.
        balance:    Current balance or None.
        stale:      True when using cached data.
    """
    bal_val = balance or 0.0
    bal_label = "BAL (CACHED)" if stale else "BALANCE"
    lines = [
        status_bar,
        SEP,
        "💼 *WALLET OVERVIEW* — LIVE MODE",
        SEP,
        render_kv_line("ADDRESS", f"`{address or 'N/A'}`"),
        render_kv_line(bal_label, f"${bal_val:,.4f}"),
        SEP,
        render_insight("Live balance fetched" if not stale else "Using cached balance — retry pending"),
    ]
    return "\n".join(lines)


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
        text = "\n".join([
            status_bar,
            SEP,
            "💼 *WALLET OVERVIEW*",
            SEP,
            render_kv_line("STATUS", "⚠️ N/A"),
            SEP,
            render_insight("Wallet service unavailable — check configuration"),
        ])
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
        text = _live_wallet_screen(status_bar, address, balance, stale=False)
        return text, build_wallet_menu()

    except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
        if isinstance(exc, asyncio.CancelledError):
            raise
        log.warning("handle_wallet_timeout", user_id=user_id)
    except Exception as exc:
        log.error("handle_wallet_error", user_id=user_id, error=str(exc))

    status_bar = _get_status_bar()
    return _live_wallet_screen(status_bar, _cached_address, _cached_balance, stale=True), build_wallet_menu()


async def handle_paper_wallet(mode: str = "default") -> tuple[str, list]:
    """Return full paper wallet terminal card.

    Shows: cash, locked, equity, buying power, exposure, realized PnL,
    unrealized PnL, open position count. Uses WalletEngine DB state.
    """
    if _paper_wallet_engine is None:
        log.warning("handle_paper_wallet_no_engine")
        status_bar = _get_status_bar()
        return (
            "\n".join([
                status_bar,
                SEP,
                "💼 *WALLET OVERVIEW* — PAPER MODE",
                SEP,
                render_kv_line("STATUS", "⚠️ Engine unavailable"),
                SEP,
                render_insight("Paper wallet engine not injected — restart bot"),
            ]),
            build_wallet_menu(),
        )

    metrics = _collect_paper_metrics()
    if metrics is None:
        return "⚠️ Data unavailable", build_paper_wallet_menu()

    cash, locked, equity, realized_pnl, unrealized_pnl, open_count = metrics

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
            "\n".join([
                status_bar,
                SEP,
                "💼 *WALLET OVERVIEW*",
                SEP,
                render_kv_line("STATUS", "⚠️ N/A"),
                SEP,
                render_insight("Wallet service unavailable — check configuration"),
            ]),
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
            text = "\n".join([
                status_bar,
                SEP,
                "💼 *WALLET OVERVIEW* — LIVE MODE",
                SEP,
                render_kv_line("ADDRESS", f"`{address or 'N/A'}`"),
                render_kv_line("BALANCE", f"${balance or 0.0:,.4f}"),
                render_kv_line("LOCKED", "$0.0000"),
                render_kv_line("EQUITY", f"${balance or 0.0:,.4f}"),
                SEP,
                render_insight("Live balance fetched successfully"),
            ])
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
            "\n".join([
                status_bar,
                SEP,
                "💼 *WALLET OVERVIEW* — LIVE MODE",
                SEP,
                render_kv_line("BAL (CACHED)", f"${_cached_balance:,.4f}"),
                SEP,
                render_insight("Using cached balance — live fetch failed, retrying"),
            ]),
            build_wallet_menu(),
        )
    status_bar = _get_status_bar()
    return (
        "\n".join([
            status_bar,
            SEP,
            "⚠️ *SYSTEM NOTICE*",
            SEP,
            render_kv_line("STATUS", "Balance unavailable"),
            "_All retry attempts exhausted._",
            SEP,
            render_insight("Wallet fetch failed — check network and API keys"),
        ]),
        build_wallet_menu(),
    )


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
            text = "\n".join([
                status_bar,
                SEP,
                "💸 *WITHDRAW — PAPER SIMULATION*",
                SEP,
                render_kv_line("AVAILABLE", f"${ws.cash:,.4f}"),
                render_kv_line("LOCKED", f"${ws.locked:,.4f}"),
                SEP,
                "_Use `/withdraw <amount>` to simulate deduction._",
                "_(No real funds will move — paper mode only)_",
                render_insight("Paper simulation — no real funds at risk"),
            ])
        except Exception as exc:
            log.error("wallet_withdraw_paper_state_error", error=str(exc))
            text = "\n".join([
                status_bar,
                SEP,
                "⚠️ *SYSTEM NOTICE*",
                SEP,
                render_kv_line("STATUS", "State fetch error"),
                SEP,
                render_insight("Paper wallet state unavailable — retry"),
            ])
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
            "\n".join([
                status_bar,
                SEP,
                "⚠️ *SYSTEM NOTICE*",
                SEP,
                render_kv_line("STATUS", "Engine unavailable"),
                SEP,
                render_insight("Paper wallet engine not injected — restart bot"),
            ]),
            build_paper_wallet_menu(),
        )

    if amount <= 0:
        return (
            "\n".join([
                status_bar,
                SEP,
                "⚠️ *SYSTEM NOTICE*",
                SEP,
                render_kv_line("STATUS", "Invalid amount"),
                "_Amount must be greater than zero._",
                SEP,
                render_insight("Provide a positive withdrawal amount"),
            ]),
            build_paper_wallet_menu(),
        )

    try:
        state_before = _paper_wallet_engine.get_state()
        if state_before.cash < amount:
            return (
                "\n".join([
                    status_bar,
                    SEP,
                    "⚠️ *WITHDRAW REJECTED*",
                    SEP,
                    render_kv_line("REQUESTED", f"${amount:,.4f}"),
                    render_kv_line("AVAILABLE", f"${state_before.cash:,.4f}"),
                    SEP,
                    "_Insufficient funds. Cannot withdraw._",
                    render_insight("Reduce withdrawal amount or close positions"),
                ]),
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
            "\n".join([
                status_bar,
                SEP,
                "✅ *PAPER WITHDRAWAL SIMULATED*",
                SEP,
                render_kv_line("WITHDRAWN", f"-${amount:,.4f}"),
                render_kv_line("CASH NOW", f"${new_state.cash:,.4f}"),
                render_kv_line("EQUITY", f"${new_state.equity:,.4f}"),
                SEP,
                "_No real funds moved — paper simulation only._",
                render_insight("Simulation complete — equity updated"),
            ]),
            build_paper_wallet_menu(),
        )
    except InsufficientFundsError as exc:
        log.warning("paper_withdraw_insufficient_funds", amount=amount, error=str(exc))
        return (
            "\n".join([
                status_bar,
                SEP,
                "⚠️ *WITHDRAW FAILED*",
                SEP,
                render_kv_line("REASON", "Insufficient funds"),
                SEP,
                render_insight("Reduce withdrawal amount or close positions"),
            ]),
            build_paper_wallet_menu(),
        )
    except Exception as exc:
        log.error("paper_withdraw_unexpected_error", amount=amount, error=str(exc))
        return (
            "\n".join([
                status_bar,
                SEP,
                "⚠️ *SYSTEM NOTICE*",
                SEP,
                render_kv_line("STATUS", "Withdraw error"),
                "_An unexpected error occurred._",
                SEP,
                render_insight("System encountered an issue — retry shortly"),
            ]),
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
