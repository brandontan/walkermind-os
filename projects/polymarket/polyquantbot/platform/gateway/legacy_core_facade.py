from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..context.models import PlatformContextEnvelope
from ..context.resolver import ContextResolver, LegacySessionSeed


@dataclass(frozen=True)
class LegacyCoreFacadeResolution:
    """Deterministic facade output for boundary consumers."""

    context_envelope: PlatformContextEnvelope | None
    source: str
    activated: bool


@runtime_checkable
class LegacyCoreFacade(Protocol):
    """Stable seam between platform-facing gateway code and legacy-core surfaces."""

    def resolve_context(self, seed: LegacySessionSeed) -> LegacyCoreFacadeResolution:
        """Resolve platform context through a legacy-core backed adapter or deterministic fallback."""


class LegacyCoreResolverAdapter:
    """Legacy-backed adapter shell that delegates to the read-only ContextResolver."""

    def __init__(self, resolver: ContextResolver | None = None) -> None:
        self._resolver = resolver or ContextResolver()

    def resolve_context(self, seed: LegacySessionSeed) -> LegacyCoreFacadeResolution:
        envelope = self._resolver.resolve(seed)
        return LegacyCoreFacadeResolution(
            context_envelope=envelope,
            source="legacy-context-resolver",
            activated=True,
        )


class LegacyCoreFacadeDisabled:
    """Deterministic fallback when facade activation is intentionally disabled."""

    def resolve_context(self, seed: LegacySessionSeed) -> LegacyCoreFacadeResolution:
        _ = seed
        return LegacyCoreFacadeResolution(
            context_envelope=None,
            source="disabled",
            activated=False,
        )
