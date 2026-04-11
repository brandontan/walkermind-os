from __future__ import annotations

from .facade_factory import build_legacy_core_facade
from .public_app_gateway import PublicAppGateway, normalize_public_gateway_mode


def build_public_app_gateway(*, mode: str | None = None) -> PublicAppGateway:
    """Build Phase 2.7 public app gateway seam in a strictly non-activating mode."""

    normalized_mode = normalize_public_gateway_mode(mode)
    legacy_core_facade = build_legacy_core_facade(mode=normalized_mode)
    return PublicAppGateway(
        mode=normalized_mode,
        legacy_core_facade=legacy_core_facade,
        runtime_routing_active=False,
    )
