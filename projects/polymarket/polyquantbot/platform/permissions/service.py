from __future__ import annotations

from ..storage.models import PermissionProfileRecord, utc_now
from ..storage.repositories import PermissionProfileRepository
from .models import PermissionProfile


class PermissionService:
    """Permission profile resolver with optional persistence.

    Read/write separation:
    - resolve_permission_profile: pure read — returns existing record or in-memory default, NEVER writes.
    - ensure_permission_profile: write path — returns existing record or creates + persists a new one.
    """

    def __init__(self, repository: PermissionProfileRepository | None = None) -> None:
        self._repository = repository

    def resolve_permission_profile(
        self,
        *,
        user_id: str,
        allowed_markets: tuple[str, ...],
        mode: str,
    ) -> PermissionProfile:
        """Read-only: return existing profile or transient default. Never writes."""
        if self._repository is not None:
            existing = self._repository.get_by_user_id(user_id=user_id)
            if existing is not None:
                return PermissionProfile(**existing.__dict__)

        normalized_mode = mode.strip().upper()
        record = PermissionProfileRecord(
            user_id=user_id,
            allowed_markets=allowed_markets,
            live_enabled=normalized_mode == "LIVE",
            paper_enabled=normalized_mode != "LIVE",
            max_notional_cap=5_000.0,
            max_positions_cap=5,
            version="phase2-foundation",
            updated_at=utc_now(),
        )
        return PermissionProfile(**record.__dict__)

    def ensure_permission_profile(
        self,
        *,
        user_id: str,
        allowed_markets: tuple[str, ...],
        mode: str,
    ) -> PermissionProfile:
        """Write path: return existing profile or create + persist a new one."""
        if self._repository is not None:
            existing = self._repository.get_by_user_id(user_id=user_id)
            if existing is not None:
                return PermissionProfile(**existing.__dict__)

        normalized_mode = mode.strip().upper()
        record = PermissionProfileRecord(
            user_id=user_id,
            allowed_markets=allowed_markets,
            live_enabled=normalized_mode == "LIVE",
            paper_enabled=normalized_mode != "LIVE",
            max_notional_cap=5_000.0,
            max_positions_cap=5,
            version="phase2-foundation",
            updated_at=utc_now(),
        )
        if self._repository is not None:
            self._repository.upsert(record)
        return PermissionProfile(**record.__dict__)
