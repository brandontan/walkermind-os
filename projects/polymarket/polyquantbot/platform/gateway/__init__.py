"""Platform gateway boundary contracts and deterministic facade foundations."""

from .facade_factory import (
    LEGACY_CORE_FACADE_CONTEXT_RESOLVER,
    LEGACY_CORE_FACADE_DISABLED,
    LEGACY_CORE_FACADE_MODE_ENV,
    build_legacy_core_facade,
)
from .legacy_core_facade import (
    LegacyCoreFacade,
    LegacyCoreFacadeDisabled,
    LegacyCoreFacadeResolution,
    LegacyCoreResolverAdapter,
)

__all__ = [
    "LEGACY_CORE_FACADE_CONTEXT_RESOLVER",
    "LEGACY_CORE_FACADE_DISABLED",
    "LEGACY_CORE_FACADE_MODE_ENV",
    "LegacyCoreFacade",
    "LegacyCoreFacadeDisabled",
    "LegacyCoreFacadeResolution",
    "LegacyCoreResolverAdapter",
    "build_legacy_core_facade",
]
