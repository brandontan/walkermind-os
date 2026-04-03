"""Wallet handler — returns (text, keyboard) for wallet-related screens.

WalletService is injected at bot startup via :func:`set_wallet_service`.
Before injection, all screens show a safe informative stub.

Return type: tuple[str, InlineKeyboard]
"""
from __future__ import annotations

from typing import Optional, TYPE_CHECKING

import structlog

from ..ui.keyboard import build_wallet_menu
from ..ui.screens import (
    wallet_screen,
    wallet_balance_screen,
    wallet_exposure_screen,
    wallet_withdraw_screen,
    wallet_withdraw_result_screen,
)

if TYPE_CHECKING:
    from ...core.wallet.service import WalletService

log = structlog.get_logger(__name__)

# Module-level WalletService reference — injected at bot startup
_wallet_service: Optional["WalletService"] = None


def set_wallet_service(service: "WalletService") -> None:
    """Inject the WalletService into the wallet handler.

    Call once at bot startup from main.py after WalletService is initialised.
    """
    global _wallet_service  # noqa: PLW0603
    _wallet_service = service
    log.info("wallet_handler_service_injected")


async def handle_wallet(mode: str, user_id: Optional[int] = None) -> tuple[str, list]:
    """Return wallet overview screen with live address and balance."""
    if _wallet_service is None or user_id is None:
        return wallet_screen(mode=mode), build_wallet_menu()

    try:
        wallet = await _wallet_service.get_wallet(user_id)
        if wallet is None:
            # Auto-create on first access
            wallet = await _wallet_service.create_wallet(user_id)
        balance = await _wallet_service.get_balance(user_id)
        return wallet_screen(mode=mode, address=wallet.address, balance=balance), build_wallet_menu()
    except Exception as exc:
        log.error("handle_wallet_error", user_id=user_id, error=str(exc))
        return wallet_screen(mode=mode), build_wallet_menu()


async def handle_wallet_balance(user_id: Optional[int] = None) -> tuple[str, list]:
    """Return balance detail screen with live data."""
    if _wallet_service is None or user_id is None:
        return wallet_balance_screen(), build_wallet_menu()

    try:
        wallet = await _wallet_service.get_wallet(user_id)
        balance = await _wallet_service.get_balance(user_id)
        address = wallet.address if wallet else None
        return wallet_balance_screen(balance=balance, address=address), build_wallet_menu()
    except Exception as exc:
        log.error("handle_wallet_balance_error", user_id=user_id, error=str(exc))
        return wallet_balance_screen(), build_wallet_menu()


async def handle_wallet_exposure(user_id: Optional[int] = None) -> tuple[str, list]:
    """Return open exposure detail screen."""
    return wallet_exposure_screen(), build_wallet_menu()


async def handle_wallet_withdraw(user_id: Optional[int] = None) -> tuple[str, list]:
    """Return withdraw initiation screen showing address and available balance."""
    if _wallet_service is None or user_id is None:
        return wallet_withdraw_screen(), build_wallet_menu()

    try:
        wallet = await _wallet_service.get_wallet(user_id)
        balance = await _wallet_service.get_balance(user_id)
        address = wallet.address if wallet else None
        return wallet_withdraw_screen(address=address, balance=balance), build_wallet_menu()
    except Exception as exc:
        log.error("handle_wallet_withdraw_error", user_id=user_id, error=str(exc))
        return wallet_withdraw_screen(), build_wallet_menu()


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
