from __future__ import annotations

from projects.polymarket.polyquantbot.platform.gateway.gateway_factory import (
    build_public_app_gateway,
    resolve_public_app_gateway_mode,
)
from projects.polymarket.polyquantbot.platform.gateway.public_app_gateway import PublicAppGateway


def create_public_app_gateway(*, mode: str | None = None) -> PublicAppGateway:
    """Create the Phase 2.7 public/app gateway skeleton with safe defaults."""

    selected_mode = resolve_public_app_gateway_mode(mode)
    return build_public_app_gateway(mode=selected_mode)
