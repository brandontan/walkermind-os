from __future__ import annotations

from ..platform.context.resolver import ContextResolver
from ..platform.gateway import PublicAppGateway, build_public_app_gateway


def build_api_gateway_boundary(
    *,
    mode: str | None = None,
    resolver: ContextResolver | None = None,
) -> PublicAppGateway:
    """API-facing composition boundary for future dual-mode gateway routing."""

    return build_public_app_gateway(mode=mode, resolver=resolver)
