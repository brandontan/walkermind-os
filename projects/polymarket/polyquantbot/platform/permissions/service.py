from __future__ import annotations

from .models import PermissionProfile


class PermissionService:
    """Read-only permission scaffold for Phase 1 contract validation."""

    def resolve_permission_profile(
        self,
        *,
        user_id: str,
        allowed_markets: tuple[str, ...],
        mode: str,
    ) -> PermissionProfile:
        normalized_mode = mode.strip().upper()
        return PermissionProfile(
            user_id=user_id,
            allowed_markets=allowed_markets,
            live_enabled=normalized_mode == "LIVE",
            paper_enabled=normalized_mode != "LIVE",
            max_notional_cap=5_000.0,
            max_positions_cap=5,
        )
