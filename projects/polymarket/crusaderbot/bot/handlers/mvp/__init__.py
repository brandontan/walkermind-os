"""MVP v1 Telegram handlers (blueprint surfaces).

Each module exports an `attach(application)` function for the dispatcher to
call, plus a `top_*` entry function used by the persistent main-menu and
existing handlers that delegate to the new MVP surface.
"""
from . import dashboard, autotrade, copy_wallet, portfolio, markets, settings, help as help_h, onboarding

__all__ = [
    "dashboard",
    "autotrade",
    "copy_wallet",
    "portfolio",
    "markets",
    "settings",
    "help_h",
    "onboarding",
]
