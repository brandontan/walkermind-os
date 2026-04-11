from __future__ import annotations

import os

from ..context.resolver import ContextResolver
from .facade_factory import build_legacy_core_facade
from .legacy_core_facade import LegacyCoreFacade
from .public_app_gateway import (
    PUBLIC_APP_GATEWAY_DISABLED,
    PUBLIC_APP_GATEWAY_LEGACY_FACADE,
    PublicAppGateway,
    PublicAppGatewayConfig,
    PublicAppGatewayDisabled,
    PublicAppGatewayLegacyFacade,
)

PUBLIC_APP_GATEWAY_MODE_ENV = "PLATFORM_PUBLIC_APP_GATEWAY_MODE"


def parse_public_app_gateway_mode(mode: str | None = None) -> str:
    """Parse gateway mode deterministically with safe default fallback."""

    selected = (mode or os.getenv(PUBLIC_APP_GATEWAY_MODE_ENV, PUBLIC_APP_GATEWAY_DISABLED)).strip().lower()
    if selected in {PUBLIC_APP_GATEWAY_DISABLED, PUBLIC_APP_GATEWAY_LEGACY_FACADE}:
        return selected
    return PUBLIC_APP_GATEWAY_DISABLED


def build_public_app_gateway(
    *,
    mode: str | None = None,
    facade: LegacyCoreFacade | None = None,
    resolver: ContextResolver | None = None,
) -> PublicAppGateway:
    """Build foundation-only app/public gateway seam without enabling runtime routing."""

    selected_mode = parse_public_app_gateway_mode(mode)
    config = PublicAppGatewayConfig(mode=selected_mode)
    if selected_mode == PUBLIC_APP_GATEWAY_LEGACY_FACADE:
        selected_facade = facade or build_legacy_core_facade(mode="legacy-context-resolver", resolver=resolver)
        return PublicAppGatewayLegacyFacade(facade=selected_facade, config=config)
    return PublicAppGatewayDisabled(config=config)
