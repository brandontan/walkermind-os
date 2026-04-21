"""Backend-managed Falcon configuration contract for public paper beta."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class FalconSettings:
    enabled: bool
    api_key: str | None
    base_url: str
    timeout_seconds: float

    def api_key_configured(self) -> bool:
        return bool((self.api_key or "").strip())

    @classmethod
    def from_env(cls) -> "FalconSettings":
        enabled = os.getenv("FALCON_ENABLED", "false").strip().lower() == "true"
        api_key = os.getenv("FALCON_API_KEY", "").strip()
        base_url = os.getenv("FALCON_BASE_URL", "https://narrative.agent.heisenberg.so").strip()
        timeout_raw = os.getenv("FALCON_TIMEOUT", "8").strip() or "8"
        timeout_seconds = float(timeout_raw)

        if timeout_seconds <= 0:
            raise RuntimeError("FALCON_TIMEOUT must be > 0")
        if enabled and not base_url:
            raise RuntimeError("FALCON_BASE_URL is required when FALCON_ENABLED=true")

        return cls(
            enabled=enabled,
            api_key=api_key,
            base_url=base_url.rstrip("/"),
            timeout_seconds=timeout_seconds,
        )
