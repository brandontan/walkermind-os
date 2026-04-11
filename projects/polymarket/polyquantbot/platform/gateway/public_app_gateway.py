from __future__ import annotations

from dataclasses import dataclass

from .facade_factory import (
    LEGACY_CORE_FACADE_CONTEXT_RESOLVER,
    LEGACY_CORE_FACADE_DISABLED,
)
from .legacy_core_facade import LegacyCoreFacade


@dataclass(frozen=True)
class PublicAppGateway:
    """Foundation seam for Phase 2.7; intentionally non-activating at runtime."""

    mode: str
    legacy_core_facade: LegacyCoreFacade
    runtime_routing_active: bool = False


def normalize_public_gateway_mode(mode: str | None) -> str:
    """Fail-closed mode normalization for foundation-only gateway seam."""

    normalized_mode = (mode or "").strip().lower()
    if normalized_mode == LEGACY_CORE_FACADE_CONTEXT_RESOLVER:
        return LEGACY_CORE_FACADE_CONTEXT_RESOLVER
    return LEGACY_CORE_FACADE_DISABLED
