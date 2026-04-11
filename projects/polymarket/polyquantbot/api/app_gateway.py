from __future__ import annotations

from projects.polymarket.polyquantbot.platform.gateway.gateway_factory import build_public_app_gateway
from projects.polymarket.polyquantbot.platform.gateway.public_app_gateway import PublicAppGateway


def get_app_gateway(*, mode: str | None = None) -> PublicAppGateway:
    """Compose the public app gateway seam without activating runtime routing."""

    return build_public_app_gateway(mode=mode)
