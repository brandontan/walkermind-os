from __future__ import annotations

from pathlib import Path

import pytest

from projects.polymarket.polyquantbot.platform.context.resolver import LegacySessionSeed
from projects.polymarket.polyquantbot.platform.gateway import (
    PUBLIC_APP_GATEWAY_DISABLED,
    PUBLIC_APP_GATEWAY_LEGACY_ONLY,
    PUBLIC_APP_GATEWAY_PLATFORM_GATEWAY_PRIMARY,
    PUBLIC_APP_GATEWAY_PLATFORM_GATEWAY_SHADOW,
    PublicAppGatewayConfig,
    PublicAppGatewayLegacyFacade,
    PublicAppGatewayPlatformGatewayPrimary,
    PublicAppGatewayPlatformGatewayShadow,
    build_legacy_core_facade,
    build_public_app_gateway,
    parse_public_app_gateway_mode,
)


def _seed() -> LegacySessionSeed:
    return LegacySessionSeed(
        user_id="phase2-9-user",
        external_user_id="phase2-9-external",
        mode="PAPER",
        wallet_binding_id="phase2-9-wallet",
        wallet_type="LEGACY_SESSION",
        signature_type="SESSION",
        funder_address="0xphase29",
        auth_state="UNVERIFIED",
        allowed_markets=("MKT-2-9",),
        trace_id="phase2-9-trace",
    )


def test_phase2_9_invalid_mode_fails_closed() -> None:
    with pytest.raises(ValueError, match="invalid_gateway_mode"):
        parse_public_app_gateway_mode("not-real")


def test_phase2_9_default_mode_remains_non_activating() -> None:
    gateway = build_public_app_gateway()
    resolution = gateway.resolve(_seed())

    assert resolution.mode == PUBLIC_APP_GATEWAY_DISABLED
    assert resolution.activated is False
    assert resolution.runtime_routing_active is False
    assert resolution.routing_trace.platform_participated is False
    assert resolution.routing_trace.runtime_activation_remained_disabled is True


def test_phase2_9_legacy_only_selects_legacy_path() -> None:
    gateway = build_public_app_gateway(mode=PUBLIC_APP_GATEWAY_LEGACY_ONLY)
    resolution = gateway.resolve(_seed())

    assert isinstance(gateway, PublicAppGatewayLegacyFacade)
    assert resolution.mode == PUBLIC_APP_GATEWAY_LEGACY_ONLY
    assert resolution.source == PUBLIC_APP_GATEWAY_LEGACY_ONLY
    assert resolution.facade_resolution is not None
    assert resolution.routing_trace.selected_path == PUBLIC_APP_GATEWAY_LEGACY_ONLY
    assert resolution.routing_trace.platform_participated is False


def test_phase2_9_shadow_mode_includes_platform_path_but_stays_inactive() -> None:
    gateway = build_public_app_gateway(mode=PUBLIC_APP_GATEWAY_PLATFORM_GATEWAY_SHADOW)
    resolution = gateway.resolve(_seed())

    assert isinstance(gateway, PublicAppGatewayPlatformGatewayShadow)
    assert resolution.mode == PUBLIC_APP_GATEWAY_PLATFORM_GATEWAY_SHADOW
    assert resolution.activated is False
    assert resolution.runtime_routing_active is False
    assert resolution.routing_trace.platform_participated is True
    assert resolution.routing_trace.runtime_activation_remained_disabled is True


def test_phase2_9_primary_contract_is_structural_and_inactive() -> None:
    gateway = build_public_app_gateway(mode=PUBLIC_APP_GATEWAY_PLATFORM_GATEWAY_PRIMARY)
    resolution = gateway.resolve(_seed())

    assert isinstance(gateway, PublicAppGatewayPlatformGatewayPrimary)
    assert resolution.mode == PUBLIC_APP_GATEWAY_PLATFORM_GATEWAY_PRIMARY
    assert resolution.activated is False
    assert resolution.runtime_routing_active is False
    assert resolution.routing_trace.platform_participated is True


def test_phase2_9_platform_routing_raises_when_adapter_enforcement_fails() -> None:
    facade = build_legacy_core_facade(mode="legacy-context-resolver")
    gateway = PublicAppGatewayPlatformGatewayShadow(
        facade=facade,
        config=PublicAppGatewayConfig(
            mode=PUBLIC_APP_GATEWAY_PLATFORM_GATEWAY_SHADOW,
            activation_requested=False,
        ),
    )
    facade.assert_adapter_usage = lambda: False  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="adapter_not_used_in_platform_gateway_path"):
        gateway.resolve(_seed())


def test_phase2_9_platform_routing_raises_on_active_routing_attempt() -> None:
    facade = build_legacy_core_facade(mode="legacy-context-resolver")
    gateway = PublicAppGatewayPlatformGatewayPrimary(
        facade=facade,
        config=PublicAppGatewayConfig(
            mode=PUBLIC_APP_GATEWAY_PLATFORM_GATEWAY_PRIMARY,
            activation_requested=True,
        ),
    )

    with pytest.raises(RuntimeError, match="attempted_active_routing_without_explicit_safe_contract"):
        gateway.resolve(_seed())


def test_phase2_9_gateway_has_no_direct_core_import_regression() -> None:
    gateway_source = Path(
        "/workspace/walker-ai-team/projects/polymarket/polyquantbot/platform/gateway/public_app_gateway.py"
    ).read_text(encoding="utf-8")

    assert "projects.polymarket.polyquantbot.core" not in gateway_source
    assert "from ...core" not in gateway_source
