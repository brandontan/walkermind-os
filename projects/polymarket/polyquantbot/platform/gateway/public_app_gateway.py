from __future__ import annotations

from dataclasses import dataclass

from .legacy_core_facade import LegacyCoreFacade


@dataclass(frozen=True)
class PublicAppGateway:
    """Foundation-only public/app gateway skeleton for Phase 2.7.

    This seam is intentionally non-activating. It can compose legacy facade
    dependencies for follow-up phases without enabling runtime routing.
    """

    mode: str
    legacy_core_facade: LegacyCoreFacade
    runtime_routing_active: bool = False

    def is_active(self) -> bool:
        """Return deterministic runtime activation state for this skeleton."""

        return self.runtime_routing_active
