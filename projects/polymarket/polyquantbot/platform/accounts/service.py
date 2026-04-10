from __future__ import annotations

from .models import UserAccount
from ..storage.models import UserAccountRecord, utc_now
from ..storage.repositories import UserAccountRepository


class AccountService:
    """Account contract provider with optional Phase 2 persistence."""

    def __init__(self, repository: UserAccountRepository | None = None) -> None:
        self._repository = repository

    def resolve_user_account(self, *, legacy_user_id: str, source_type: str = "legacy") -> UserAccount:
        normalized_user_id = legacy_user_id.strip() or "legacy-default"
        if self._repository is not None:
            existing = self._repository.get_by_user_id(user_id=normalized_user_id)
            if existing is not None:
                return UserAccount(**existing.__dict__)
        return UserAccount(**self._build_record(legacy_user_id=legacy_user_id, source_type=source_type).__dict__)

    def ensure_user_account(self, *, legacy_user_id: str, source_type: str = "legacy") -> UserAccount:
        resolved = self.resolve_user_account(legacy_user_id=legacy_user_id, source_type=source_type)
        if self._repository is not None:
            self._repository.upsert(UserAccountRecord(**resolved.__dict__))
        return resolved

    @staticmethod
    def _build_record(*, legacy_user_id: str, source_type: str) -> UserAccountRecord:
        normalized_user_id = legacy_user_id.strip() or "legacy-default"
        now = utc_now()
        return UserAccountRecord(
            user_id=normalized_user_id,
            external_user_id=legacy_user_id,
            source_type=source_type,
            status="active",
            created_at=now,
            updated_at=now,
        )
