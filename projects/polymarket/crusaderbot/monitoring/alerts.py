"""Telegram operator-alert dispatcher with cooldown + consecutive-failure gating.

Triggers:
- /health returns "down" or "degraded" for ``CONSECUTIVE_FAIL_THRESHOLD`` checks.
- Fly.io machine restart detected (lifespan startup event).
- Any required dependency unreachable at startup.

Anti-spam:
- ``COOLDOWN_SECONDS`` between alerts of the same type.
- Per-(alert_type, check_name) tracking — independent cooldown per dimension.

Implementation notes:
- Reuses the PTB Bot instance registered by ``main.py`` via ``notifications`` —
  this module never instantiates a new bot.
- All timestamps are UTC ``time.monotonic()`` deltas; absolute walltime is used
  only for the human-readable message body.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from .. import notifications
from ..config import get_settings

logger = logging.getLogger(__name__)

# --- tuning constants -------------------------------------------------------
COOLDOWN_SECONDS: float = 5 * 60.0
CONSECUTIVE_FAIL_THRESHOLD: int = 2

# --- module state -----------------------------------------------------------
# Last walltime an alert of a given (type, key) was dispatched.
_last_alert_at: dict[tuple[str, str], float] = {}
# Consecutive-failure counter per check name, used by ``record_health_result``.
_consecutive_failures: dict[str, int] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _cooldown_active(alert_type: str, key: str) -> bool:
    last = _last_alert_at.get((alert_type, key))
    if last is None:
        return False
    return (time.monotonic() - last) < COOLDOWN_SECONDS


async def _dispatch(alert_type: str, key: str, body: str) -> bool:
    """Send a plain-text alert to ``OPERATOR_CHAT_ID`` if not in cooldown.

    Returns ``True`` when the alert was dispatched, ``False`` if suppressed.

    No lock is used: the cooldown record is updated synchronously before the
    network call, so a worst-case race produces at most one duplicate alert
    per cooldown window — preferable to coupling the dispatcher to a single
    asyncio loop instance.
    """
    if _cooldown_active(alert_type, key):
        logger.debug(
            "alert suppressed by cooldown type=%s key=%s", alert_type, key,
        )
        return False
    _last_alert_at[(alert_type, key)] = time.monotonic()

    chat_id: Optional[int] = get_settings().OPERATOR_CHAT_ID
    if not chat_id:
        logger.error("alert dispatch skipped — OPERATOR_CHAT_ID not set")
        return False
    # plain text: parse_mode=None — values must not be re-interpreted as Markdown.
    await notifications.send(chat_id, body, parse_mode=None)
    return True


async def alert_startup(restart_detected: bool = True) -> None:
    """Notify the operator that the process has just started (Fly machine boot)."""
    body = (
        f"[CrusaderBot] startup\n"
        f"time: {_now_iso()}\n"
        f"event: {'machine_restart' if restart_detected else 'cold_start'}"
    )
    await _dispatch("startup", "boot", body)


async def alert_dependency_unreachable(check_name: str, reason: str) -> None:
    """Notify the operator that a required dependency was unreachable at boot."""
    body = (
        f"[CrusaderBot] dependency unreachable at startup\n"
        f"time: {_now_iso()}\n"
        f"check: {check_name}\n"
        f"reason: {reason}"
    )
    await _dispatch("startup_dep_fail", check_name, body)


async def alert_health_degraded(
    overall_status: str, failing: dict[str, str],
) -> None:
    """Notify the operator that /health is reporting degraded/down state.

    ``failing`` maps check name -> error reason (only non-ok checks).
    """
    if not failing:
        return
    lines = [
        f"[CrusaderBot] health alert: {overall_status}",
        f"time: {_now_iso()}",
        "failing checks:",
    ]
    for name, reason in failing.items():
        lines.append(f"  - {name}: {reason}")
    # Cooldown key reflects the failing-check signature so that a NEW failure
    # mode is alerted immediately rather than swallowed by an active cooldown.
    key = ",".join(sorted(failing.keys())) or "unknown"
    await _dispatch("health_degraded", f"{overall_status}:{key}", "\n".join(lines))


async def record_health_result(result: dict) -> None:
    """Update consecutive-failure counters and dispatch alerts when threshold is hit.

    Call this after every /health evaluation that runs in a background loop or
    inside the route handler when the operator opts into request-driven alerts.
    """
    status = result.get("status", "down")
    checks = result.get("checks", {}) or {}
    failing = {k: v for k, v in checks.items() if v != "ok"}

    if status == "ok":
        # Reset all counters — system has recovered.
        for name in list(_consecutive_failures.keys()):
            _consecutive_failures[name] = 0
        return

    # Per-check reset: any check that is OK this round breaks its own
    # consecutive-failure streak even if the overall verdict is still
    # degraded because some OTHER dependency is still down. Without this
    # reset, a single failing check could keep the system in "degraded" long
    # enough for an unrelated check's stale counter to trip the threshold on
    # a later isolated failure and page the operator falsely.
    for name in list(_consecutive_failures.keys()):
        if name not in failing:
            _consecutive_failures[name] = 0

    # Increment counters only for the checks that actually failed.
    for name in failing:
        _consecutive_failures[name] = _consecutive_failures.get(name, 0) + 1

    # Alert only when at least one failing check has crossed the threshold.
    breached = {
        name: reason
        for name, reason in failing.items()
        if _consecutive_failures.get(name, 0) >= CONSECUTIVE_FAIL_THRESHOLD
    }
    if breached:
        await alert_health_degraded(status, breached)


async def _run_health_record_safely(result: dict) -> None:
    """Background-task wrapper that swallows + logs alert dispatch failures.

    Used by ``schedule_health_record`` so a failed Telegram call never
    surfaces as an unhandled task exception or affects the /health response
    that already returned to the caller.
    """
    try:
        await record_health_result(result)
    except Exception as exc:  # noqa: BLE001 — must not raise from a bg task
        logger.error("background alert dispatch failed: %s", exc, exc_info=True)


def schedule_health_record(result: dict) -> Optional[asyncio.Task]:
    """Schedule ``record_health_result`` on the running loop and return.

    The /health route MUST NOT await alert delivery: ``notifications.send``
    retries with exponential backoff (3 attempts, up to several seconds
    per attempt) before returning, which can exceed Fly's 5-second probe
    timeout when Telegram is slow/unreachable and turn a degradable
    dependency into failed health probes + machine restarts.

    Returns the created Task, or ``None`` when there is no running loop
    (test/sync contexts) so callers can no-op safely without a try/except.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    return loop.create_task(_run_health_record_safely(result))


def reset_state() -> None:
    """Clear cooldown + counter state. Test-only entrypoint."""
    _last_alert_at.clear()
    _consecutive_failures.clear()
