"""Wallet handler — returns (text, keyboard) for wallet-related screens.

WalletService is injected at bot startup via :func:`set_wallet_service`.
Before injection, all screens show a safe informative stub.

Return type: tuple[str, InlineKeyboard]
"""
from __future__ import annotations

import asyncio
from typing import Optional, TYPE_CHECKING

import structlog

from ..ui.keyboard import build_wallet_menu, build_paper_wallet_menu
from ..ui.screens import (
    wallet_screen,
    wallet_balance_screen,
    wallet_exposure_screen,
    wallet_withdraw_screen,
    wallet_withdraw_result_screen,
)

if TYPE_CHECKING:
    from ...core.wallet.service import WalletService
    from ...core.wallet_engine import WalletEngine

log = structlog.get_logger(__name__)

_BALANCE_FETCH_TIMEOUT_S: float = 2.0

# Module-level WalletService reference — injected at bot startup
_wallet_service: Optional["WalletService"] = None
# Last known balance — used as fallback when API is unavailable
_cached_balance: Optional[float] = None
_cached_address: Optional[str] = None

# Paper wallet engine — injected at bot startup (optional)
_paper_wallet_engine: Optional["WalletEngine"] = None


def set_paper_wallet_engine(engine: "WalletEngine") -> None:
    """Inject the WalletEngine (paper trading) into the wallet handler.

    Call once at bot startup after WalletEngine is initialised.
    Does NOT affect the existing blockchain WalletService.
    """
    global _paper_wallet_engine  # noqa: PLW0603
    _paper_wallet_engine = engine
    log.info("wallet_handler_paper_engine_injected")


def set_wallet_service(service: "WalletService") -> None:
    """Inject the WalletService into the wallet handler.

    Call once at bot startup from main.py after WalletService is initialised.
    """
    global _wallet_service  # noqa: PLW0603
    _wallet_service = service
    log.info("wallet_handler_service_injected")


async def handle_wallet(mode: str, user_id: Optional[int] = None) -> tuple[str, list]:
    """Return wallet overview screen with live address and balance."""
    global _cached_balance, _cached_address  # noqa: PLW0603
    if _wallet_service is None or user_id is None:
        return wallet_screen(mode=mode, balance=_cached_balance, address=_cached_address), build_wallet_menu()

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
        return wallet_screen(mode=mode, address=address, balance=balance), build_wallet_menu()
    except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
        if isinstance(exc, asyncio.CancelledError):
            raise
        log.warning("handle_wallet_timeout", user_id=user_id)
        return wallet_screen(mode=mode, address=_cached_address, balance=_cached_balance), build_wallet_menu()
    except Exception as exc:
        log.error("handle_wallet_error", user_id=user_id, error=str(exc))
        return wallet_screen(mode=mode, address=_cached_address, balance=_cached_balance), build_wallet_menu()


async def handle_wallet_balance(user_id: Optional[int] = None) -> tuple[str, list]:
    """Return balance detail screen with live data.

    Retries up to 3 times with 0.5 s back-off.  Each attempt is guarded by a
    2 s timeout.  Falls back to the last cached balance on total failure.
    """
    global _cached_balance, _cached_address  # noqa: PLW0603
    if _wallet_service is None or user_id is None:
        return wallet_balance_screen(balance=_cached_balance, address=_cached_address), build_wallet_menu()

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
            log.info(
                "wallet_fetch",
                status="success",
                user_id=user_id,
                balance=balance,
                attempt=attempt,
            )
            return wallet_balance_screen(balance=balance, address=address), build_wallet_menu()
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError:
            log.warning(
                "wallet_fetch",
                status="timeout",
                user_id=user_id,
                attempt=attempt,
            )
        except Exception as exc:
            log.warning(
                "wallet_fetch",
                status="error",
                user_id=user_id,
                attempt=attempt,
                error=str(exc),
            )
        if attempt < 3:
            await asyncio.sleep(0.5 * attempt)

    log.error("wallet_fetch_all_retries_exhausted", status="failed", user_id=user_id)
    # Fallback to cached balance rather than empty error screen
    if _cached_balance is not None:
        log.info("wallet_fetch_using_cached_balance", balance=_cached_balance)
        return wallet_balance_screen(balance=_cached_balance, address=_cached_address), build_wallet_menu()
    return "❌ Failed to fetch wallet", build_wallet_menu()


async def handle_wallet_exposure(user_id: Optional[int] = None) -> tuple[str, list]:
    """Return open exposure detail screen."""
    return wallet_exposure_screen(), build_wallet_menu()


async def handle_wallet_withdraw(user_id: Optional[int] = None) -> tuple[str, list]:
    """Return withdraw initiation screen showing address and available balance."""
    global _cached_balance, _cached_address  # noqa: PLW0603
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


async def handle_withdraw_command(
    user_id: Optional[int],
    to_address: str,
    amount_usdc: float,
) -> tuple[str, list]:
    """Execute a USDC withdrawal and return the result screen.

    Called when the user sends ``/withdraw <to_address> <amount>``.

    Args:
        user_id: Telegram user ID.
        to_address: Destination ``0x…`` Ethereum address (42 chars).
        amount_usdc: Amount in USDC (must be > 0).

    Returns:
        ``(screen_text, keyboard)`` — always returns a tuple even on error.
    """
    if _wallet_service is None or user_id is None:
        return wallet_withdraw_screen(), build_wallet_menu()

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
        error_text = (
            "❌ *Withdraw Failed*\n\n"
            f"`{exc}`\n\n"
            "_Check address format and available balance._"
        )
        return error_text, build_wallet_menu()
    except Exception as exc:
        log.error("withdraw_command_unexpected_error", user_id=user_id, error=str(exc))
        return wallet_withdraw_screen(), build_wallet_menu()


async def handle_paper_wallet(mode: str = "default") -> tuple[str, list]:
    """Return paper wallet overview screen showing cash, locked, equity, and unrealized PnL.

    This function uses the injected :class:`~core.wallet_engine.WalletEngine`
    (paper trading engine) — it does NOT touch the blockchain WalletService.
    Reflects the persisted wallet state on every call.

    Args:
        mode: Display mode hint (reserved for future use).

    Returns:
        ``(screen_text, keyboard)`` tuple.
    """
    if _paper_wallet_engine is None:
        log.warning("handle_paper_wallet_no_engine")
        return (
            "⚠️ *Paper Wallet*\n\n_Paper wallet engine not available._",
            build_wallet_menu(),
        )

    try:
        state = _paper_wallet_engine.get_state()
    except Exception as exc:
        log.error("handle_paper_wallet_state_error", error=str(exc))
        return "❌ *Error fetching paper wallet state*", build_wallet_menu()

    # Compute total unrealized PnL from all open positions (if available)
    _unrealized: float = 0.0
    _open_count: int = 0
    try:
        from ...execution.engine_router import get_engine_container  # noqa: PLC0415
        _ec = get_engine_container()
        _positions = _ec.paper_positions.get_all_open()
        _unrealized = sum(p.unrealized_pnl for p in _positions)
        _open_count = len(_positions)
    except Exception:
        pass

    _unreal_sign = "+" if _unrealized >= 0 else ""
    text = (
        "💼 *Paper Wallet*\n\n"
        f"💵 Cash (available): *${state.cash:,.2f}*\n"
        f"🔒 Locked (in positions): *${state.locked:,.2f}*\n"
        f"📊 Equity (total): *${state.equity:,.2f}*\n"
        f"📈 Open Positions: *{_open_count}*\n"
        f"💹 Unrealized PnL: *{_unreal_sign}{_unrealized:.4f} USD*\n\n"
        f"_Paper trading mode — no real funds at risk._"
    )

    log.info(
        "handle_paper_wallet_displayed",
        cash=state.cash,
        locked=state.locked,
        equity=state.equity,
        unrealized_pnl=_unrealized,
        open_positions=_open_count,
        mode=mode,
    )
    return text, build_paper_wallet_menu()
