from __future__ import annotations

import os

from ..context.resolver import ContextResolver
from .facade_factory import LEGACY_CORE_FACADE_CONTEXT_RESOLVER, build_legacy_core_facade
from .public_app_gateway import (
    PUBLIC_APP_GATEWAY_DISABLED,
    PUBLIC_APP_GATEWAY_LEGACY_ONLY,
    PUBLIC_APP_GATEWAY_PLATFORM_GATEWAY_PRIMARY,
    PUBLIC_APP_GATEWAY_PLATFORM_GATEWAY_SHADOW,
    PUBLIC_APP_GATEWAY_LEGACY_FACADE,
    PublicAppGateway,
    PublicAppGatewayConfig,
    PublicAppGatewayDisabled,
    PublicAppGatewayLegacyFacade,
    PublicAppGatewayPlatformGatewayPrimary,
    PublicAppGatewayPlatformGatewayShadow,
)

PUBLIC_APP_GATEWAY_MODE_ENV = "PLATFORM_PUBLIC_APP_GATEWAY_MODE"


def parse_public_app_gateway_mode(mode: str | None = None) -> str:
    """Parse gateway mode deterministically with fail-closed semantics."""

    selected = (mode or os.getenv(PUBLIC_APP_GATEWAY_MODE_ENV, PUBLIC_APP_GATEWAY_DISABLED)).strip().lower()
    alias_map = {
        PUBLIC_APP_GATEWAY_LEGACY_FACADE: PUBLIC_APP_GATEWAY_LEGACY_ONLY,
    }
    normalized = alias_map.get(selected, selected)
    supported_modes = {
        PUBLIC_APP_GATEWAY_DISABLED,
        PUBLIC_APP_GATEWAY_LEGACY_ONLY,
        PUBLIC_APP_GATEWAY_PLATFORM_GATEWAY_SHADOW,
        PUBLIC_APP_GATEWAY_PLATFORM_GATEWAY_PRIMARY,
    }
    if normalized not in supported_modes:
        raise ValueError(f"invalid_gateway_mode:{selected}")
    return normalized


def build_public_app_gateway(
    *,
    mode: str | None = None,
    resolver: ContextResolver | None = None,
) -> PublicAppGateway:
    """Build foundation-only app/public gateway seam without enabling runtime routing."""

    selected_mode = parse_public_app_gateway_mode(mode)
    config = PublicAppGatewayConfig(mode=selected_mode, activation_requested=False)
    if selected_mode == PUBLIC_APP_GATEWAY_LEGACY_ONLY:
        selected_facade = build_legacy_core_facade(
            mode=LEGACY_CORE_FACADE_CONTEXT_RESOLVER,
            resolver=resolver,
        )
        return PublicAppGatewayLegacyFacade(facade=selected_facade, config=config)
    if selected_mode == PUBLIC_APP_GATEWAY_PLATFORM_GATEWAY_SHADOW:
        selected_facade = build_legacy_core_facade(
            mode=LEGACY_CORE_FACADE_CONTEXT_RESOLVER,
            resolver=resolver,
        )
        return PublicAppGatewayPlatformGatewayShadow(facade=selected_facade, config=config)
    if selected_mode == PUBLIC_APP_GATEWAY_PLATFORM_GATEWAY_PRIMARY:
        selected_facade = build_legacy_core_facade(
            mode=LEGACY_CORE_FACADE_CONTEXT_RESOLVER,
            resolver=resolver,
        )
        return PublicAppGatewayPlatformGatewayPrimary(facade=selected_facade, config=config)
    return PublicAppGatewayDisabled(config=config)
