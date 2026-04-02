"""Wallet handler — returns (text, keyboard) for wallet-related screens.

WalletManager is not yet wired in main.py.  Screens show available data
and redirect to /health for live exposure until the integration is complete.

Return type: tuple[str, InlineKeyboard]
"""
from __future__ import annotations

from ..ui.keyboard import build_wallet_menu
from ..ui.screens import wallet_screen, wallet_balance_screen, wallet_exposure_screen


async def handle_wallet(mode: str) -> tuple[str, list]:
    """Return wallet overview screen."""
    return wallet_screen(mode=mode), build_wallet_menu()


async def handle_wallet_balance() -> tuple[str, list]:
    """Return balance detail screen."""
    # Balance data requires WalletManager wiring — show informative stub
    return wallet_balance_screen(), build_wallet_menu()


async def handle_wallet_exposure() -> tuple[str, list]:
    """Return open exposure detail screen."""
    # Exposure data requires WalletManager wiring — show informative stub
    return wallet_exposure_screen(), build_wallet_menu()
