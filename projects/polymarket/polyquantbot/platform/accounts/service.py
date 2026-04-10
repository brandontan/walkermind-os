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
        return self._build_default_account(
            legacy_user_id=legacy_user_id,
            normalized_user_id=normalized_user_id,
            source_type=source_type,
        )

    def ensure_user_account(self, *, legacy_user_id: str, source_type: str = "legacy") -> UserAccount:
        account = self.resolve_user_account(legacy_user_id=legacy_user_id, source_type=source_type)
        if self._repository is not None:
            self._repository.upsert(UserAccountRecord(**account.__dict__))
        return account

    @staticmethod
    def _build_default_account(
        *,
        legacy_user_id: str,
        normalized_user_id: str,
        source_type: str,
    ) -> UserAccount:
        now = utc_now()
        return UserAccount(
            user_id=normalized_user_id,
            external_user_id=legacy_user_id,
            source_type=source_type,
            status="active",
            created_at=now,
            updated_at=now,
        )
