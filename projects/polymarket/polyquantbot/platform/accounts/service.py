from __future__ import annotations

from datetime import datetime, timezone

from .models import UserAccount


class AccountService:
    """Read-only account contract provider for Phase 1 bridge integration."""

    def resolve_user_account(self, *, legacy_user_id: str, source_type: str = "legacy") -> UserAccount:
        now = datetime.now(tz=timezone.utc)
        normalized_user_id = legacy_user_id.strip() or "legacy-default"
        return UserAccount(
            user_id=normalized_user_id,
            external_user_id=legacy_user_id,
            source_type=source_type,
            status="active",
            created_at=now,
            updated_at=now,
        )
