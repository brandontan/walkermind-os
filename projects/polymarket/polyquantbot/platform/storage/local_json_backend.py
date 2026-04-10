from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class LocalJsonBackend:
    """Deterministic dev-safe JSON storage backend."""

    def __init__(self, storage_path: str) -> None:
        self._storage_file = Path(storage_path)
        self._storage_file.parent.mkdir(parents=True, exist_ok=True)
        if not self._storage_file.exists():
            self._write({})

    def load_namespace(self, namespace: str) -> dict[str, Any]:
        root = self._read()
        data = root.get(namespace)
        if isinstance(data, dict):
            return data
        return {}

    def save_namespace(self, namespace: str, payload: dict[str, Any]) -> None:
        root = self._read()
        root[namespace] = payload
        self._write(root)

    def _read(self) -> dict[str, Any]:
        raw = self._storage_file.read_text(encoding="utf-8")
        if not raw.strip():
            return {}
        loaded = json.loads(raw)
        if isinstance(loaded, dict):
            return loaded
        return {}

    def _write(self, payload: dict[str, Any]) -> None:
        self._storage_file.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
