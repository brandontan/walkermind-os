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
