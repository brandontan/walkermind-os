from __future__ import annotations

import os

from .facade_factory import (
    LEGACY_CORE_FACADE_CONTEXT_RESOLVER,
    LEGACY_CORE_FACADE_DISABLED,
    LEGACY_CORE_FACADE_MODE_ENV,
    build_legacy_core_facade,
)
from .public_app_gateway import PublicAppGateway

PUBLIC_APP_GATEWAY_MODE_ENV = "PLATFORM_PUBLIC_APP_GATEWAY_MODE"
PUBLIC_APP_GATEWAY_MODE_DISABLED = LEGACY_CORE_FACADE_DISABLED
PUBLIC_APP_GATEWAY_MODE_LEGACY_FACADE = "legacy-facade"


def resolve_public_app_gateway_mode(mode: str | None = None) -> str:
    """Normalize public/app gateway mode with safe fallback semantics."""

    raw_mode = mode if mode is not None else os.getenv(PUBLIC_APP_GATEWAY_MODE_ENV, PUBLIC_APP_GATEWAY_MODE_DISABLED)
    normalized = raw_mode.strip().lower()
    if normalized in {PUBLIC_APP_GATEWAY_MODE_DISABLED, PUBLIC_APP_GATEWAY_MODE_LEGACY_FACADE}:
        return normalized
    return PUBLIC_APP_GATEWAY_MODE_DISABLED


def build_public_app_gateway(*, mode: str | None = None) -> PublicAppGateway:
    """Build Phase 2.7 public/app gateway skeleton without runtime activation."""

    selected_mode = resolve_public_app_gateway_mode(mode)
    facade_mode = (
        LEGACY_CORE_FACADE_CONTEXT_RESOLVER
        if selected_mode == PUBLIC_APP_GATEWAY_MODE_LEGACY_FACADE
        else LEGACY_CORE_FACADE_DISABLED
    )
    facade = build_legacy_core_facade(mode=facade_mode)
    return PublicAppGateway(
        mode=selected_mode,
        legacy_core_facade=facade,
        runtime_routing_active=False,
    )
