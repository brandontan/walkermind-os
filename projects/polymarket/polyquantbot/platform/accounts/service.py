from __future__ import annotations

from .models import UserAccount
from ..storage.models import UserAccountRecord, utc_now
from ..storage.repositories import UserAccountRepository


class AccountService:
    """Account contract provider with optional Phase 2 persistence.

    Read/write separation:
    - resolve_user_account: pure read — returns existing record or in-memory default, NEVER writes.
    - ensure_user_account: write path — returns existing record or creates + persists a new one.
    """

    def __init__(self, repository: UserAccountRepository | None = None) -> None:
        self._repository = repository

    def resolve_user_account(self, *, legacy_user_id: str, source_type: str = "legacy") -> UserAccount:
        """Read-only: return existing account or transient default. Never writes."""
        normalized_user_id = legacy_user_id.strip() or "legacy-default"
        if self._repository is not None:
            existing = self._repository.get_by_user_id(user_id=normalized_user_id)
            if existing is not None:
                return UserAccount(**existing.__dict__)
        now = utc_now()
        record = UserAccountRecord(
            user_id=normalized_user_id,
            external_user_id=legacy_user_id,
            source_type=source_type,
            status="active",
            created_at=now,
            updated_at=now,
        )
        return UserAccount(**record.__dict__)

    def ensure_user_account(self, *, legacy_user_id: str, source_type: str = "legacy") -> UserAccount:
        """Write path: return existing account or create + persist a new one."""
        normalized_user_id = legacy_user_id.strip() or "legacy-default"
        if self._repository is not None:
            existing = self._repository.get_by_user_id(user_id=normalized_user_id)
            if existing is not None:
                return UserAccount(**existing.__dict__)
        now = utc_now()
        record = UserAccountRecord(
            user_id=normalized_user_id,
            external_user_id=legacy_user_id,
            source_type=source_type,
            status="active",
            created_at=now,
            updated_at=now,
        )
        if self._repository is not None:
            self._repository.upsert(record)
        return UserAccount(**record.__dict__)
