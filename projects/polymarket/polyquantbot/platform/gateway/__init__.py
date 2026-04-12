"""Platform gateway boundary contracts and deterministic facade foundations."""

from .facade_factory import (
    LEGACY_CORE_FACADE_CONTEXT_RESOLVER,
    LEGACY_CORE_FACADE_DISABLED,
    LEGACY_CORE_FACADE_MODE_ENV,
    build_legacy_core_facade,
)
from .gateway_factory import (
    PUBLIC_APP_GATEWAY_MODE_ENV,
    build_public_app_gateway,
    parse_public_app_gateway_mode,
)
from .legacy_core_facade import (
    LegacyCoreFacade,
    LegacyCoreFacadeDisabled,
    LegacyCoreFacadeResolution,
    LegacyCoreResolverAdapter,
)
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
    PublicAppGatewayResolution,
    PublicAppGatewayRoutingTrace,
)

__all__ = [
    "LEGACY_CORE_FACADE_CONTEXT_RESOLVER",
    "LEGACY_CORE_FACADE_DISABLED",
    "LEGACY_CORE_FACADE_MODE_ENV",
    "LegacyCoreFacade",
    "PUBLIC_APP_GATEWAY_DISABLED",
    "PUBLIC_APP_GATEWAY_LEGACY_ONLY",
    "PUBLIC_APP_GATEWAY_PLATFORM_GATEWAY_PRIMARY",
    "PUBLIC_APP_GATEWAY_PLATFORM_GATEWAY_SHADOW",
    "PUBLIC_APP_GATEWAY_LEGACY_FACADE",
    "PUBLIC_APP_GATEWAY_MODE_ENV",
    "LegacyCoreFacadeDisabled",
    "LegacyCoreFacadeResolution",
    "LegacyCoreResolverAdapter",
    "build_legacy_core_facade",
    "build_public_app_gateway",
    "parse_public_app_gateway_mode",
    "PublicAppGateway",
    "PublicAppGatewayConfig",
    "PublicAppGatewayDisabled",
    "PublicAppGatewayLegacyFacade",
    "PublicAppGatewayPlatformGatewayPrimary",
    "PublicAppGatewayPlatformGatewayShadow",
    "PublicAppGatewayResolution",
    "PublicAppGatewayRoutingTrace",
]
