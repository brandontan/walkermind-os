from __future__ import annotations

import os

from projects.polymarket.polyquantbot.api.app_gateway import create_public_app_gateway
from projects.polymarket.polyquantbot.platform.gateway.facade_factory import (
    LEGACY_CORE_FACADE_CONTEXT_RESOLVER,
    LEGACY_CORE_FACADE_DISABLED,
)
from projects.polymarket.polyquantbot.platform.gateway.gateway_factory import (
    PUBLIC_APP_GATEWAY_MODE_DISABLED,
    PUBLIC_APP_GATEWAY_MODE_ENV,
    PUBLIC_APP_GATEWAY_MODE_LEGACY_FACADE,
    resolve_public_app_gateway_mode,
)


def test_phase2_7_gateway_disabled_mode_stays_non_activating() -> None:
    os.environ.pop(PUBLIC_APP_GATEWAY_MODE_ENV, None)
    gateway = create_public_app_gateway(mode=PUBLIC_APP_GATEWAY_MODE_DISABLED)

    assert gateway.mode == PUBLIC_APP_GATEWAY_MODE_DISABLED
    assert gateway.is_active() is False

    resolution = gateway.legacy_core_facade.resolve_context(seed=_seed())
    assert resolution.activated is False
    assert resolution.source == LEGACY_CORE_FACADE_DISABLED
    assert resolution.context_envelope is None


def test_phase2_7_gateway_legacy_facade_mode_builds_seam_without_runtime_activation() -> None:
    gateway = create_public_app_gateway(mode=PUBLIC_APP_GATEWAY_MODE_LEGACY_FACADE)

    assert gateway.mode == PUBLIC_APP_GATEWAY_MODE_LEGACY_FACADE
    assert gateway.is_active() is False

    resolution = gateway.legacy_core_facade.resolve_context(seed=_seed())
    assert resolution.activated is True
    assert resolution.source == LEGACY_CORE_FACADE_CONTEXT_RESOLVER
    assert resolution.context_envelope is not None


def test_phase2_7_gateway_invalid_mode_falls_back_to_disabled() -> None:
    assert resolve_public_app_gateway_mode("INVALID") == PUBLIC_APP_GATEWAY_MODE_DISABLED

    os.environ[PUBLIC_APP_GATEWAY_MODE_ENV] = "BAD-MODE"
    try:
        gateway = create_public_app_gateway()
    finally:
        os.environ.pop(PUBLIC_APP_GATEWAY_MODE_ENV, None)

    assert gateway.mode == PUBLIC_APP_GATEWAY_MODE_DISABLED
    assert gateway.is_active() is False
    resolution = gateway.legacy_core_facade.resolve_context(seed=_seed())
    assert resolution.source == LEGACY_CORE_FACADE_DISABLED
    assert resolution.activated is False


def _seed() -> "LegacySessionSeed":
    from projects.polymarket.polyquantbot.platform.context.resolver import LegacySessionSeed

    return LegacySessionSeed(
        user_id="gateway-user",
        external_user_id="gateway-external-user",
        mode="PAPER",
        wallet_binding_id="gateway-wallet",
        wallet_type="LEGACY_SESSION",
        signature_type="SESSION",
        funder_address="gateway-funder",
        auth_state="UNVERIFIED",
        allowed_markets=("MKT-GATEWAY",),
        trace_id="trace-gateway",
    )
