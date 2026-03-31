"""Phase 10.6 — SystemState: Trading system execution state machine.

Defines the three valid runtime states for the trading system and
a thread-safe (asyncio-only) manager that enforces state transitions.

States:
    RUNNING — normal operation, orders may be submitted.
    PAUSED  — temporary halt, no new orders; may resume to RUNNING.
    HALTED  — terminal kill state, no recovery (requires manual restart).

State transition rules::

    RUNNING → PAUSED    (pause command or non-critical safety trigger)
    RUNNING → HALTED    (kill command or critical failure)
    PAUSED  → RUNNING   (resume command, only if kill switch is inactive)
    PAUSED  → HALTED    (kill command)
    HALTED  → (none)    terminal — no transitions out

Usage::

    manager = SystemStateManager()
    await manager.pause("operator_command")
    await manager.resume()
    await manager.halt("daily_loss_limit_breached")

    if not manager.is_execution_allowed():
        return  # do not submit orders

Thread-safety: single asyncio event loop only.
"""
from __future__ import annotations

import asyncio
import time
from enum import Enum
from typing import Optional

import structlog

log = structlog.get_logger()


class SystemState(str, Enum):
    """Valid runtime states for the trading system."""

    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    HALTED = "HALTED"


class SystemStateManager:
    """Asyncio-safe system state machine.

    Manages RUNNING / PAUSED / HALTED transitions with full audit logging.
    All transition methods are idempotent: re-entering the current state
    is a no-op and returns without error.

    Args:
        initial_state: Starting state (default: RUNNING).
    """

    def __init__(self, initial_state: SystemState = SystemState.RUNNING) -> None:
        self._state = initial_state
        self._lock = asyncio.Lock()
        self._state_changed_at: float = time.time()
        self._reason: str = "initialized"

        log.info(
            "system_state_manager_initialized",
            state=self._state.value,
        )

    # ── Read-only accessors ────────────────────────────────────────────────────

    @property
    def state(self) -> SystemState:
        """Current system state (snapshot, no lock needed for read)."""
        return self._state

    @property
    def reason(self) -> str:
        """Reason for the most recent state transition."""
        return self._reason

    def is_execution_allowed(self) -> bool:
        """Return True only when the system is in RUNNING state.

        Orders MUST NOT be submitted unless this returns True.

        Returns:
            True if RUNNING, False if PAUSED or HALTED.
        """
        return self._state is SystemState.RUNNING

    def snapshot(self) -> dict:
        """Return a JSON-serialisable state snapshot.

        Returns:
            Dict with state, reason, and timestamp.
        """
        return {
            "state": self._state.value,
            "reason": self._reason,
            "state_changed_at": self._state_changed_at,
        }

    # ── Transition methods ─────────────────────────────────────────────────────

    async def pause(self, reason: str = "operator_command") -> None:
        """Transition to PAUSED state.

        Idempotent: no-op if already PAUSED.
        Blocked: no-op if already HALTED (cannot un-halt via pause).

        Args:
            reason: Human-readable reason for the pause.
        """
        async with self._lock:
            if self._state is SystemState.HALTED:
                log.warning(
                    "system_state_pause_blocked_halted",
                    current=self._state.value,
                )
                return
            if self._state is SystemState.PAUSED:
                log.debug("system_state_already_paused")
                return

            prev = self._state
            self._state = SystemState.PAUSED
            self._reason = reason
            self._state_changed_at = time.time()
            log.warning(
                "system_state_paused",
                previous=prev.value,
                reason=reason,
            )

    async def resume(self, reason: str = "operator_resume") -> bool:
        """Transition from PAUSED to RUNNING state.

        Cannot resume from HALTED — returns False in that case.
        Idempotent: no-op if already RUNNING.

        Args:
            reason: Human-readable reason for the resume.

        Returns:
            True if transition to RUNNING succeeded, False if blocked.
        """
        async with self._lock:
            if self._state is SystemState.HALTED:
                log.warning(
                    "system_state_resume_blocked_halted",
                    reason="system is HALTED — manual restart required",
                )
                return False
            if self._state is SystemState.RUNNING:
                log.debug("system_state_already_running")
                return True

            prev = self._state
            self._state = SystemState.RUNNING
            self._reason = reason
            self._state_changed_at = time.time()
            log.info(
                "system_state_resumed",
                previous=prev.value,
                reason=reason,
            )
            return True

    async def halt(self, reason: str = "kill_command") -> None:
        """Transition to HALTED state (terminal — no recovery).

        Idempotent: no-op if already HALTED.

        Args:
            reason: Human-readable reason for the halt.
        """
        async with self._lock:
            if self._state is SystemState.HALTED:
                log.debug("system_state_already_halted")
                return

            prev = self._state
            self._state = SystemState.HALTED
            self._reason = reason
            self._state_changed_at = time.time()
            log.warning(
                "system_state_halted",
                previous=prev.value,
                reason=reason,
            )
