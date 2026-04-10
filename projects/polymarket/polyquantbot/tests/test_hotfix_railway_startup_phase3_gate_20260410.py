from __future__ import annotations

from projects.polymarket.polyquantbot.legacy.adapters.context_bridge import LegacyContextBridge


def test_railway_startup_import_chain_context_bridge_init() -> None:
    """Regression guard: bridge constructor must not fail after resolver purity changes."""

    bridge = LegacyContextBridge()
    assert bridge is not None
    assert hasattr(bridge, "_resolver")
