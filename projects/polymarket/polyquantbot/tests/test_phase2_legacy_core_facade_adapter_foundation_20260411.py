from __future__ import annotations

import os

from projects.polymarket.polyquantbot.legacy.adapters.context_bridge import LegacyContextBridge
from projects.polymarket.polyquantbot.platform.context.resolver import LegacySessionSeed
from projects.polymarket.polyquantbot.platform.gateway import (
    LEGACY_CORE_FACADE_CONTEXT_RESOLVER,
    LEGACY_CORE_FACADE_DISABLED,
    LegacyCoreFacadeDisabled,
    LegacyCoreResolverAdapter,
    build_legacy_core_facade,
)


def _seed() -> LegacySessionSeed:
    return LegacySessionSeed(
        user_id="legacy-user-adapter",
        external_user_id="external-user-adapter",
        mode="PAPER",
        wallet_binding_id="wb-adapter",
        wallet_type="LEGACY_SESSION",
        signature_type="SESSION",
        funder_address="abc123",
        auth_state="UNVERIFIED",
        allowed_markets=("MKT-ADAPTER",),
        trace_id="trace-adapter",
    )


def test_phase2_facade_import_path_continuity() -> None:
    assert LEGACY_CORE_FACADE_DISABLED == "disabled"
    assert LEGACY_CORE_FACADE_CONTEXT_RESOLVER == "legacy-context-resolver"


def test_phase2_facade_factory_uses_disabled_fallback_by_default() -> None:
    os.environ.pop("PLATFORM_LEGACY_CORE_FACADE_MODE", None)
    facade = build_legacy_core_facade()
    assert isinstance(facade, LegacyCoreFacadeDisabled)
    resolution = facade.resolve_context(_seed())
    assert resolution.activated is False
    assert resolution.context_envelope is None
    assert resolution.source == "disabled"


def test_phase2_facade_factory_constructs_legacy_backed_adapter() -> None:
    facade = build_legacy_core_facade(mode="legacy-context-resolver")
    assert isinstance(facade, LegacyCoreResolverAdapter)
    resolution = facade.resolve_context(_seed())
    assert resolution.activated is True
    assert resolution.context_envelope is not None
    assert resolution.context_envelope.execution_context.trace_id == "trace-adapter"


def test_phase2_bridge_runtime_path_unchanged_when_facade_is_not_activated() -> None:
    os.environ.pop("PLATFORM_LEGACY_CORE_FACADE_MODE", None)
    os.environ["ENABLE_PLATFORM_CONTEXT_BRIDGE"] = "true"
    try:
        bridge = LegacyContextBridge()
        result = bridge.attach_context(seed=_seed())
        assert result.attached is True
        assert result.context is not None
        assert result.context.execution_context.trace_id == "trace-adapter"
        assert result.context.wallet_context.wallet_binding_id == "wb-adapter"
    finally:
        os.environ.pop("ENABLE_PLATFORM_CONTEXT_BRIDGE", None)
