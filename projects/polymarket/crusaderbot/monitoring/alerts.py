"""Telegram operator-alert dispatcher with cooldown + consecutive-failure gating.

Triggers:
- /health returns "down" or "degraded" for ``CONSECUTIVE_FAIL_THRESHOLD`` checks.
- Fly.io machine restart detected (lifespan startup event).
- Any required dependency unreachable at startup.
- Exit watcher: TP / SL / force-close executed (per-user notification),
  close-attempt persistent failure (operator notification at
  ``CLOSE_FAILURE_OPERATOR_THRESHOLD`` consecutive failures on the same
  position).

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
import html
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from .. import notifications
from ..config import get_settings

logger = logging.getLogger(__name__)

# --- tuning constants -------------------------------------------------------
COOLDOWN_SECONDS: float = 5 * 60.0
CONSECUTIVE_FAIL_THRESHOLD: int = 2
# Consecutive close-attempt failures on the same position before paging the
# operator. Per R12c spec: "alert operator when close_failed persists > 2
# consecutive ticks". We page exactly at the threshold and rely on the
# per-position cooldown key to suppress repeats.
CLOSE_FAILURE_OPERATOR_THRESHOLD: int = 2

# --- module state -----------------------------------------------------------
# Last walltime an alert of a given (type, key) was dispatched.
_last_alert_at: dict[tuple[str, str], float] = {}
# Consecutive-failure counter per check name, used by ``record_health_result``.
_consecutive_failures: dict[str, int] = {}

_STARTUP_LOCK = "/tmp/.crusaderbot_last_startup_alert"
_STARTUP_COOLDOWN = 10 * 60  # 10 minutes — suppress within same machine instance


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _cooldown_active(alert_type: str, key: str) -> bool:
    last = _last_alert_at.get((alert_type, key))
    if last is None:
        return False
    return (time.monotonic() - last) < COOLDOWN_SECONDS


async def _dispatch(alert_type: str, key: str, body: str) -> bool:
    """Send a plain-text alert to ``OPERATOR_CHAT_ID`` if not in cooldown.

    Returns ``True`` when the alert was successfully dispatched, ``False``
    if suppressed by cooldown, missing chat target, or permanent send
    failure.

    The cooldown timestamp is recorded ONLY after a successful delivery —
    so a Telegram outage will not silence the operator for the next 5
    minutes. The trade-off is a small race window in which two concurrent
    callers can both pass the cooldown check and both deliver; that is
    preferable to missing alerts during an outage.
    """
    if _cooldown_active(alert_type, key):
        logger.debug(
            "alert suppressed by cooldown type=%s key=%s", alert_type, key,
        )
        return False

    chat_id: Optional[int] = get_settings().OPERATOR_CHAT_ID
    if not chat_id:
        logger.error("alert dispatch skipped — OPERATOR_CHAT_ID not set")
        return False
    # plain text: parse_mode=None — values must not be re-interpreted as Markdown.
    delivered = await notifications.send(chat_id, body, parse_mode=None)
    if not delivered:
        logger.warning(
            "alert dispatch failed — cooldown NOT armed type=%s key=%s",
            alert_type, key,
        )
        return False
    _last_alert_at[(alert_type, key)] = time.monotonic()
    return True


async def alert_startup(restart_detected: bool = True) -> None:
    """Notify the operator that the process has just started (Fly machine boot).

    Suppressed if a startup alert was dispatched within _STARTUP_COOLDOWN seconds
    on this machine instance (/tmp persists within instance, not across deploys).
    """
    try:
        if os.path.exists(_STARTUP_LOCK):
            with open(_STARTUP_LOCK) as f:
                last_ts = float(f.read().strip())
            if (time.time() - last_ts) < _STARTUP_COOLDOWN:
                logger.debug("startup alert suppressed by /tmp lock (cooldown active)")
                return
    except Exception as exc:
        logger.warning("startup lock read failed — proceeding without cooldown: %s", exc)

    body = (
        f"[CrusaderBot][admin] startup event\n"
        f"time: {_now_iso()}\n"
        f"event: {'restart' if restart_detected else 'cold_start'}"
    )
    dispatched = await _dispatch("startup", "boot", body)

    if dispatched:
        try:
            with open(_STARTUP_LOCK, "w") as f:
                f.write(str(time.time()))
        except Exception as exc:
            logger.warning("startup lock write failed — next restart will alert again: %s", exc)


async def alert_dependency_unreachable(check_name: str, reason: str) -> None:
    """Notify the operator that a required dependency was unreachable at boot."""
    body = (
        f"[CrusaderBot] dependency unreachable at startup\n"
        f"time: {_now_iso()}\n"
        f"check: {check_name}\n"
        f"reason: {reason}"
    )
    await _dispatch("startup_dep_fail", check_name, body)


async def alert_missing_env(keys: list[str]) -> None:
    """Single aggregated alert for any number of missing required env vars.

    Per-variable alerts collide on the ``("startup_dep_fail", "env")``
    cooldown key, so a boot with N missing vars would page the operator
    only once and silently swallow the rest. Aggregating into one message
    surfaces every missing key in a single actionable line, and the
    cooldown key is derived from the sorted missing set so a DIFFERENT
    set of missing keys on a later boot pages immediately.
    """
    if not keys:
        return
    body = (
        f"[CrusaderBot] required env vars missing at startup\n"
        f"time: {_now_iso()}\n"
        f"keys:\n  - " + "\n  - ".join(keys)
    )
    cooldown_key = ",".join(sorted(keys))
    await _dispatch("startup_missing_env", cooldown_key, body)


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


def _log_task_exception(task: "asyncio.Task") -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error(
            "background alert failed: %s", exc,
            exc_info=(type(exc), exc, exc.__traceback__),
        )


def schedule_alert(coro) -> Optional[asyncio.Task]:
    """Fire-and-forget wrapper for any alert coroutine.

    Used by the lifespan boot path so the same retry/backoff chain that
    blocks ``/health`` cannot block ``app.startup`` either — Fly's
    ``grace_period`` is now 10s, so a slow Telegram during boot would
    otherwise turn a notification outage into failed startup probes and
    restart loops.

    The coroutine itself is scheduled as the task body (rather than wrapped
    in another ``async def``), so cancellation cleanly closes it without
    leaving an un-awaited coroutine. A done-callback logs any exception at
    ERROR. Returns ``None`` and closes the coro when no event loop is
    running, so test/sync callers no-op safely.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        coro.close()
        return None
    task = loop.create_task(coro)
    task.add_done_callback(_log_task_exception)
    return task


def reset_state() -> None:
    """Clear cooldown + counter state. Test-only entrypoint."""
    _last_alert_at.clear()
    _consecutive_failures.clear()


# --- exit-watcher alerts ----------------------------------------------------
# These bypass the operator cooldown channel: each user-side alert is keyed
# by position_id so two distinct closes never collide on a shared cooldown
# key. The user is paged DIRECTLY (not via OPERATOR_CHAT_ID) so multi-user
# deployments isolate notifications correctly.

def _format_exit_label(market_question: Optional[str], market_id: str) -> str:
    """Human-friendly market label for user-facing alerts (HTML-escaped)."""
    return html.escape(market_question or market_id)


async def alert_user_tp_hit(
    *,
    telegram_user_id: int,
    market_id: str,
    market_question: Optional[str],
    side: str,
    exit_price: float,
    pnl_usdc: float,
    mode: str,
) -> None:
    """Notify the position owner that TP was hit and the close was submitted."""
    label = _format_exit_label(market_question, market_id)
    text = (
        f"\U0001f3af <b>[{html.escape(mode.upper())}] TP hit</b>\n"
        f"{label}\n"
        f"Side: <b>{html.escape(side.upper())}</b> — Exit: <code>{exit_price:.3f}</code>\n"
        f"P&amp;L: <b>${pnl_usdc:+.2f}</b>"
    )
    await notifications.send(telegram_user_id, text)


async def alert_user_sl_hit(
    *,
    telegram_user_id: int,
    market_id: str,
    market_question: Optional[str],
    side: str,
    exit_price: float,
    pnl_usdc: float,
    mode: str,
) -> None:
    """Notify the position owner that SL was hit and the close was submitted."""
    label = _format_exit_label(market_question, market_id)
    text = (
        f"\U0001f6d1 <b>[{html.escape(mode.upper())}] SL hit</b>\n"
        f"{label}\n"
        f"Side: <b>{html.escape(side.upper())}</b> — Exit: <code>{exit_price:.3f}</code>\n"
        f"P&amp;L: <b>${pnl_usdc:+.2f}</b>"
    )
    await notifications.send(telegram_user_id, text)


async def alert_user_force_close(
    *,
    telegram_user_id: int,
    market_id: str,
    market_question: Optional[str],
    side: str,
    exit_price: float,
    pnl_usdc: float,
    mode: str,
) -> None:
    """Notify the position owner that an emergency force-close completed."""
    label = _format_exit_label(market_question, market_id)
    text = (
        f"\U0001f6a8 <b>[{html.escape(mode.upper())}] Force-close executed</b>\n"
        f"{label}\n"
        f"Side: <b>{html.escape(side.upper())}</b> — Exit: <code>{exit_price:.3f}</code>\n"
        f"P&amp;L: <b>${pnl_usdc:+.2f}</b>"
    )
    await notifications.send(telegram_user_id, text)


async def alert_user_strategy_exit(
    *,
    telegram_user_id: int,
    market_id: str,
    market_question: Optional[str],
    side: str,
    exit_price: float,
    pnl_usdc: float,
    mode: str,
) -> None:
    """Notify the position owner of a strategy-driven exit close."""
    label = _format_exit_label(market_question, market_id)
    text = (
        f"\U0001f4c9 <b>[{html.escape(mode.upper())}] Strategy exit</b>\n"
        f"{label}\n"
        f"Side: <b>{html.escape(side.upper())}</b> — Exit: <code>{exit_price:.3f}</code>\n"
        f"P&amp;L: <b>${pnl_usdc:+.2f}</b>"
    )
    await notifications.send(telegram_user_id, text)


async def alert_user_manual_close(
    *,
    telegram_user_id: int,
    market_id: str,
    market_question: Optional[str],
    side: str,
    exit_price: float,
    pnl_usdc: float,
    mode: str,
) -> None:
    """Notify the position owner that a manual close completed successfully."""
    label = _format_exit_label(market_question, market_id)
    text = (
        f"✅ <b>[{html.escape(mode.upper())}] Manual close</b>\n"
        f"{label}\n"
        f"Side: <b>{html.escape(side.upper())}</b> — Exit: <code>{exit_price:.3f}</code>\n"
        f"P&amp;L: <b>${pnl_usdc:+.2f}</b>"
    )
    await notifications.send(telegram_user_id, text)


async def alert_user_market_expired(
    *,
    telegram_user_id: int,
    market_id: str,
    market_question: Optional[str],
    side: str,
    size_usdc: float,
    mode: str,
) -> None:
    """Notify the position owner that the market expired and capital was returned.

    pnl_usdc is always 0.0 for expired positions — the original stake is
    returned in full, so the user needs to know their funds are safe.
    """
    label = _format_exit_label(market_question, market_id)
    text = (
        f"⏰ <b>[{html.escape(mode.upper())}] Market expired</b>\n"
        f"{label}\n"
        f"Side: <b>{html.escape(side.upper())}</b>\n"
        f"Capital returned: <b>${size_usdc:.2f} USDC</b>\n"
        "Position closed — market is no longer active on Polymarket."
    )
    await notifications.send(telegram_user_id, text)


async def alert_user_close_failed(
    *,
    telegram_user_id: int,
    market_id: str,
    market_question: Optional[str],
    side: str,
    error: str,
) -> None:
    """Notify the position owner that the close attempt failed (and will retry).

    The user-facing message intentionally avoids broker-level error detail
    that leaks internal infra; the operator alert (below) carries the full
    context for reconciliation.
    """
    label = _format_exit_label(market_question, market_id)
    text = (
        "⚠️ <b>Close attempt failed</b>\n"
        f"{label}\n"
        f"Side: <b>{html.escape(side.upper())}</b>\n"
        "We will retry on the next exit-watcher tick. If failures persist, "
        "admin has been notified."
    )
    await notifications.send(telegram_user_id, text)
    logger.warning("close_failed user-alert delivered tg=%s market=%s err=%s",
                   telegram_user_id, market_id, error[:200])


async def alert_operator_close_failed_persistent(
    *,
    position_id: UUID,
    user_id: UUID,
    market_id: str,
    side: str,
    mode: str,
    failure_count: int,
    last_error: str,
) -> None:
    """Page the operator when consecutive close failures cross the threshold.

    Fires at ``CLOSE_FAILURE_OPERATOR_THRESHOLD`` and re-fires only after
    ``COOLDOWN_SECONDS`` for the same position. Different positions never
    share a cooldown key — each one gets its own alert channel.
    """
    if failure_count < CLOSE_FAILURE_OPERATOR_THRESHOLD:
        return
    body = (
        f"[CrusaderBot] persistent close failure\n"
        f"time: {_now_iso()}\n"
        f"position: {position_id}\n"
        f"user: {user_id}\n"
        f"market: {market_id}\n"
        f"side: {side}\n"
        f"mode: {mode}\n"
        f"failures: {failure_count}\n"
        f"last_error: {last_error[:300]}"
    )
    await _dispatch("close_failed_persistent", str(position_id), body)
