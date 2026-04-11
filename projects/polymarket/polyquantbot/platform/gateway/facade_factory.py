from __future__ import annotations

import os

from ..context.resolver import ContextResolver
from .legacy_core_facade import LegacyCoreFacade, LegacyCoreFacadeDisabled, LegacyCoreResolverAdapter

LEGACY_CORE_FACADE_MODE_ENV = "PLATFORM_LEGACY_CORE_FACADE_MODE"
LEGACY_CORE_FACADE_DISABLED = "disabled"
LEGACY_CORE_FACADE_CONTEXT_RESOLVER = "legacy-context-resolver"


def build_legacy_core_facade(
    *,
    mode: str | None = None,
    resolver: ContextResolver | None = None,
) -> LegacyCoreFacade:
    """Build deterministic legacy-core facade selection for Phase 2 foundation scope."""

    selected_mode = (mode or os.getenv(LEGACY_CORE_FACADE_MODE_ENV, LEGACY_CORE_FACADE_DISABLED)).strip().lower()
    if selected_mode == LEGACY_CORE_FACADE_CONTEXT_RESOLVER:
        return LegacyCoreResolverAdapter(resolver=resolver)
    return LegacyCoreFacadeDisabled()
