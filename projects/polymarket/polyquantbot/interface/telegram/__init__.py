"""Deprecated compatibility package for legacy interface.telegram imports.

Active Telegram source of truth lives under
`projects.polymarket.polyquantbot.telegram`.
This package is kept only as a temporary shim to avoid import breakage.
"""

from projects.polymarket.polyquantbot.telegram.view_handler import render_view

__all__ = ["render_view"]
