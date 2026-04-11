from __future__ import annotations

from projects.polymarket.polyquantbot.api.app_gateway import get_app_gateway
from projects.polymarket.polyquantbot.platform.gateway import (
    LEGACY_CORE_FACADE_CONTEXT_RESOLVER,
    LEGACY_CORE_FACADE_DISABLED,
    LegacyCoreFacadeDisabled,
    LegacyCoreResolverAdapter,
)


def test_phase2_7_public_gateway_disabled_mode_is_inactive() -> None:
    gateway = get_app_gateway(mode=LEGACY_CORE_FACADE_DISABLED)

    assert gateway.mode == LEGACY_CORE_FACADE_DISABLED
    assert gateway.runtime_routing_active is False
    assert isinstance(gateway.legacy_core_facade, LegacyCoreFacadeDisabled)


def test_phase2_7_public_gateway_legacy_facade_mode_builds_seam_without_runtime_activation() -> None:
    gateway = get_app_gateway(mode=LEGACY_CORE_FACADE_CONTEXT_RESOLVER)

    assert gateway.mode == LEGACY_CORE_FACADE_CONTEXT_RESOLVER
    assert gateway.runtime_routing_active is False
    assert isinstance(gateway.legacy_core_facade, LegacyCoreResolverAdapter)


def test_phase2_7_public_gateway_invalid_mode_falls_back_to_disabled() -> None:
    gateway = get_app_gateway(mode="unsupported-mode")

    assert gateway.mode == LEGACY_CORE_FACADE_DISABLED
    assert gateway.runtime_routing_active is False
    assert isinstance(gateway.legacy_core_facade, LegacyCoreFacadeDisabled)
