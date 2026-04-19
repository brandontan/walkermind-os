"""User service foundation for multi-user user and user_settings ownership."""
from __future__ import annotations

from projects.polymarket.polyquantbot.server.schemas.multi_user import (
    ActivationStatus,
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

    def get_user_by_external_id(self, tenant_id: str, external_id: str) -> UserRecord | None:
        return self._store.get_user_by_external_id(tenant_id, external_id)

    def get_user_settings(self, user_id: str) -> UserSettingsRecord | None:
        return self._store.get_user_settings_for_user(user_id)

    def set_activation_status(
        self, user_id: str, activation_status: ActivationStatus
    ) -> UserSettingsRecord | None:
        settings = self._store.get_user_settings_for_user(user_id)
        if settings is None:
            return None
        updated = settings.model_copy(update={"activation_status": activation_status})
        self._store.put_user_settings(updated)
        return updated
