from __future__ import annotations

import os
from unittest.mock import patch

from projects.polymarket.polyquantbot.api import build_api_gateway_boundary
from projects.polymarket.polyquantbot.legacy.adapters.context_bridge import LegacyContextBridge
from projects.polymarket.polyquantbot.platform.context.resolver import LegacySessionSeed
from projects.polymarket.polyquantbot.platform.gateway import (
    LEGACY_CORE_FACADE_CONTEXT_RESOLVER,
    PUBLIC_APP_GATEWAY_DISABLED,
    PUBLIC_APP_GATEWAY_LEGACY_FACADE,
    PublicAppGatewayDisabled,
    PublicAppGatewayLegacyFacade,
    build_public_app_gateway,
    parse_public_app_gateway_mode,
)


def _seed() -> LegacySessionSeed:
    return LegacySessionSeed(
        user_id="phase2-7-user",
        external_user_id="phase2-7-external",
        mode="PAPER",
        wallet_binding_id="phase2-7-wallet",
        wallet_type="LEGACY_SESSION",
        signature_type="SESSION",
        funder_address="0xphase27",
        auth_state="UNVERIFIED",
        allowed_markets=("MKT-2-7",),
        trace_id="phase2-7-trace",
    )


def test_phase2_7_gateway_import_export_continuity() -> None:
    gateway = build_api_gateway_boundary()
    assert isinstance(gateway, PublicAppGatewayDisabled)
    assert PUBLIC_APP_GATEWAY_DISABLED == "disabled"
    assert PUBLIC_APP_GATEWAY_LEGACY_FACADE == "legacy-facade"


def test_phase2_7_gateway_default_mode_is_deterministic_non_activating() -> None:
    os.environ.pop("PLATFORM_PUBLIC_APP_GATEWAY_MODE", None)
    gateway = build_public_app_gateway()
    resolution = gateway.resolve(_seed())

    assert isinstance(gateway, PublicAppGatewayDisabled)
    assert resolution.activated is False
    assert resolution.mode == PUBLIC_APP_GATEWAY_DISABLED
    assert resolution.facade_resolution is None


def test_phase2_7_gateway_explicit_legacy_facade_construction_is_available() -> None:
    gateway = build_public_app_gateway(mode=PUBLIC_APP_GATEWAY_LEGACY_FACADE)
    resolution = gateway.resolve(_seed())

    assert isinstance(gateway, PublicAppGatewayLegacyFacade)
    assert resolution.activated is False
    assert resolution.mode == PUBLIC_APP_GATEWAY_LEGACY_FACADE
    assert resolution.facade_resolution is not None
    assert resolution.facade_resolution.activated is True



def test_phase2_7_legacy_facade_mode_composes_via_phase2_8_factory_constant() -> None:
    with patch("projects.polymarket.polyquantbot.platform.gateway.gateway_factory.build_legacy_core_facade") as mocked:
        mocked.return_value.resolve_context.return_value = None  # type: ignore[assignment]
        gateway = build_public_app_gateway(mode=PUBLIC_APP_GATEWAY_LEGACY_FACADE)
        assert isinstance(gateway, PublicAppGatewayLegacyFacade)
        mocked.assert_called_once()
        assert mocked.call_args.kwargs["mode"] == LEGACY_CORE_FACADE_CONTEXT_RESOLVER

def test_phase2_7_gateway_mode_parser_uses_safe_default_for_unknown_values() -> None:
    os.environ["PLATFORM_PUBLIC_APP_GATEWAY_MODE"] = "unknown-mode"
    try:
        assert parse_public_app_gateway_mode() == PUBLIC_APP_GATEWAY_DISABLED
        assert parse_public_app_gateway_mode("legacy-facade") == PUBLIC_APP_GATEWAY_LEGACY_FACADE
        assert parse_public_app_gateway_mode(" DISABLED ") == PUBLIC_APP_GATEWAY_DISABLED
    finally:
        os.environ.pop("PLATFORM_PUBLIC_APP_GATEWAY_MODE", None)


def test_phase2_7_default_gateway_path_has_no_runtime_drift() -> None:
    os.environ.pop("PLATFORM_PUBLIC_APP_GATEWAY_MODE", None)
    os.environ["ENABLE_PLATFORM_CONTEXT_BRIDGE"] = "true"
    try:
        gateway = build_api_gateway_boundary()
        gateway_resolution = gateway.resolve(_seed())
        assert gateway_resolution.activated is False

        bridge = LegacyContextBridge()
        bridge_result = bridge.attach_context(seed=_seed())

        assert bridge_result.attached is True
        assert bridge_result.context is not None
        assert bridge_result.context.execution_context.trace_id == "phase2-7-trace"
    finally:
        os.environ.pop("ENABLE_PLATFORM_CONTEXT_BRIDGE", None)
