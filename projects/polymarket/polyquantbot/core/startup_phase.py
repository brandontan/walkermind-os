"""Startup phase state tracking for PolyQuantBot runtime lifecycle."""
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict

import structlog

log = structlog.get_logger(__name__)


class StartupPhase(str, Enum):
    """Startup lifecycle phases for infra readiness."""

    BOOTING = "BOOTING"
    DEGRADED = "DEGRADED"
    RUNNING = "RUNNING"
    BLOCKED = "BLOCKED"


@dataclass
class StartupState:
    phase: StartupPhase
    reason: str
    updated_at: float


class StartupStateTracker:
    """Track and expose startup state transitions with structured logging."""

    def __init__(self) -> None:
        self._state = StartupState(
            phase=StartupPhase.BOOTING,
            reason="initializing",
            updated_at=time.time(),
        )
        log.info("startup_phase_initialized", **self.snapshot())

    def set_phase(self, phase: StartupPhase, reason: str) -> None:
        self._state = StartupState(
            phase=phase,
            reason=reason,
            updated_at=time.time(),
        )
        log.info("startup_phase_changed", **self.snapshot())

    def snapshot(self) -> Dict[str, Any]:
        return {
            "startup_phase": self._state.phase.value,
            "startup_reason": self._state.reason,
            "startup_updated_at": round(self._state.updated_at, 3),
        }
