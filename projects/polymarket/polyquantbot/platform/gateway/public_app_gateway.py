from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..context.resolver import LegacySessionSeed
from .legacy_core_facade import LegacyCoreFacade, LegacyCoreFacadeResolution

PUBLIC_APP_GATEWAY_DISABLED = "disabled"
PUBLIC_APP_GATEWAY_LEGACY_FACADE = "legacy-facade"


@dataclass(frozen=True)
class PublicAppGatewayConfig:
    """Deterministic gateway config for foundation-only app/public seam construction."""

    mode: str = PUBLIC_APP_GATEWAY_DISABLED


@dataclass(frozen=True)
class PublicAppGatewayResolution:
    """Boundary result contract for future app/public gateway composition (always non-activating in Phase 2.7)."""

    activated: bool
    mode: str
    source: str
    facade_resolution: LegacyCoreFacadeResolution | None


@runtime_checkable
class PublicAppGateway(Protocol):
    """Stable app-facing seam that remains non-activating by default."""

    def resolve(self, seed: LegacySessionSeed) -> PublicAppGatewayResolution:
        """Resolve through selected gateway mode without auto-activating runtime routing."""


class PublicAppGatewayDisabled:
    """Deterministic default gateway mode with no runtime activation."""

    def __init__(self, config: PublicAppGatewayConfig | None = None) -> None:
        self._config = config or PublicAppGatewayConfig(mode=PUBLIC_APP_GATEWAY_DISABLED)

    def resolve(self, seed: LegacySessionSeed) -> PublicAppGatewayResolution:
        _ = seed
        return PublicAppGatewayResolution(
            activated=False,
            mode=self._config.mode,
            source=PUBLIC_APP_GATEWAY_DISABLED,
            facade_resolution=None,
        )


class PublicAppGatewayLegacyFacade:
    """Foundation-only skeleton mode that resolves context via LegacyCoreFacade seam."""

    def __init__(self, *, facade: LegacyCoreFacade, config: PublicAppGatewayConfig | None = None) -> None:
        self._facade = facade
        self._config = config or PublicAppGatewayConfig(mode=PUBLIC_APP_GATEWAY_LEGACY_FACADE)

    def resolve(self, seed: LegacySessionSeed) -> PublicAppGatewayResolution:
        facade_resolution = self._facade.resolve_context(seed)
        return PublicAppGatewayResolution(
            activated=False,
            mode=self._config.mode,
            source=PUBLIC_APP_GATEWAY_LEGACY_FACADE,
            facade_resolution=facade_resolution,
        )
