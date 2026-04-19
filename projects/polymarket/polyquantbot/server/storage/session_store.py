"""Persistent session storage boundary for auth/session foundation."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from projects.polymarket.polyquantbot.server.schemas.auth_session import SessionContext, SessionStatus


class SessionStorageError(RuntimeError):
    """Raised when persistent session data cannot be read or written."""


class SessionStore:
    def get_session(self, session_id: str) -> SessionContext | None:
        raise NotImplementedError

    def put_session(self, session: SessionContext) -> None:
        raise NotImplementedError

    def set_session_status(self, session_id: str, status: SessionStatus) -> SessionContext:
        raise NotImplementedError


class PersistentSessionStore(SessionStore):
    """Local-file JSON session storage with deterministic overwrite semantics."""

    _FORMAT_VERSION: Final[int] = 1

    def __init__(self, storage_path: Path) -> None:
        self._storage_path = storage_path
        self._sessions: dict[str, SessionContext] = {}
        self._load_from_disk()

    def get_session(self, session_id: str) -> SessionContext | None:
        return self._sessions.get(session_id)

    def put_session(self, session: SessionContext) -> None:
        self._sessions[session.session_id] = session
        self._persist_to_disk()

    def set_session_status(self, session_id: str, status: SessionStatus) -> SessionContext:
        session = self._sessions.get(session_id)
        if session is None:
            raise SessionStorageError(f"session not found: {session_id}")

        updated = session.model_copy(update={"status": status})
        self._sessions[session_id] = updated
        self._persist_to_disk()
        return updated

    def _load_from_disk(self) -> None:
        if not self._storage_path.exists():
            return

        try:
            raw_payload = json.loads(self._storage_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SessionStorageError("persistent session store contains invalid JSON") from exc

        if not isinstance(raw_payload, dict):
            raise SessionStorageError("persistent session store payload must be an object")

        version = raw_payload.get("version")
        if version != self._FORMAT_VERSION:
            raise SessionStorageError(f"unsupported persistent session store version: {version}")

        raw_sessions = raw_payload.get("sessions")
        if not isinstance(raw_sessions, list):
            raise SessionStorageError("persistent session store sessions field must be a list")

        for item in raw_sessions:
            session = SessionContext.model_validate(item)
            self._sessions[session.session_id] = session

    def _persist_to_disk(self) -> None:
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": self._FORMAT_VERSION,
            "sessions": [
                session.model_dump(mode="json")
                for session in sorted(self._sessions.values(), key=lambda value: value.session_id)
            ],
        }

        temp_path = self._storage_path.with_suffix(f"{self._storage_path.suffix}.tmp")
        temp_path.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")
        temp_path.replace(self._storage_path)
