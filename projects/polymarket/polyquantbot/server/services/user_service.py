"""User service foundation for multi-user user and user_settings ownership."""
from __future__ import annotations

from projects.polymarket.polyquantbot.server.schemas.multi_user import (
    UserCreate,
    UserRecord,
    UserSettingsRecord,
    new_id,
    now_utc,
)
from projects.polymarket.polyquantbot.server.storage.multi_user_store import MultiUserStore


class UserService:
    def __init__(self, store: MultiUserStore) -> None:
        self._store = store

    def create_user(self, payload: UserCreate) -> tuple[UserRecord, UserSettingsRecord]:
        user = UserRecord(
            user_id=new_id("usr"),
            tenant_id=payload.tenant_id,
            external_id=payload.external_id,
            display_name=payload.display_name,
            created_at=now_utc(),
        )
        settings = UserSettingsRecord(
            settings_id=new_id("uset"),
            tenant_id=payload.tenant_id,
            user_id=user.user_id,
            created_at=now_utc(),
        )
        self._store.put_user(user)
        self._store.put_user_settings(settings)
        return user, settings

    def get_user(self, user_id: str) -> UserRecord | None:
        return self._store.get_user(user_id)
