"""WARP-82 disk-usage monitor — alert before the next disk near-miss.

Runs every 5 min via the existing AsyncIOScheduler. Queries
``pg_database_size`` and writes a ``system_alerts`` row at 70% (WARN) and 85%
(CRITICAL) of the Supabase Free-tier 500 MB cap. Same-severity alerts are
throttled to once per hour. Pure asyncio (never threading per the AGENTS.md
invariant); every error is logged + sent to Sentry and swallowed so the
scheduler/app can never be crashed by the monitor.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from ..database import get_pool

logger = logging.getLogger(__name__)

JOB_ID = "disk_monitor"

# Supabase Free-tier database-size cap and the WARN/CRITICAL thresholds.
_CAP_BYTES: int = 500 * 1024 * 1024
_WARN_BYTES: int = 350 * 1024 * 1024   # 70%
_CRIT_BYTES: int = 425 * 1024 * 1024   # 85%
_THROTTLE_SECONDS: int = 3600          # one alert per severity per hour


async def run_job(*, pool: Any | None = None) -> Optional[str]:
    """Check DB size; emit a throttled ``system_alerts`` row on threshold breach.

    Returns the severity emitted (``"warning"``/``"critical"``) or ``None`` when
    under threshold or throttled. Never raises — fail-loud to logger + Sentry,
    then swallow, so the scheduler is never crashed by the monitor.
    """
    try:
        pool = pool or get_pool()
        async with pool.acquire() as conn:  # type: ignore[attr-defined]
            bytes_used = int(await conn.fetchval(
                "SELECT pg_database_size(current_database())"
            ))
            if bytes_used >= _CRIT_BYTES:
                severity, threshold = "critical", _CRIT_BYTES
            elif bytes_used >= _WARN_BYTES:
                severity, threshold = "warning", _WARN_BYTES
            else:
                return None

            # Throttle: skip if a same-severity disk alert fired within the hour.
            throttled = await conn.fetchval(
                "SELECT 1 FROM system_alerts "
                "WHERE severity = $1 AND metadata->>'alert_type' = 'disk_usage' "
                "AND created_at > NOW() - ($2 * INTERVAL '1 second') LIMIT 1",
                severity, _THROTTLE_SECONDS,
            )
            if throttled:
                logger.info(
                    "disk_monitor: %s alert throttled (same severity within 1h) bytes=%d",
                    severity, bytes_used,
                )
                return None

            pct = round(bytes_used / _CAP_BYTES * 100.0, 1)
            mb = round(bytes_used / 1024 / 1024, 1)
            await conn.execute(
                "INSERT INTO system_alerts (severity, title, body, metadata) "
                "VALUES ($1, $2, $3, $4::jsonb)",
                severity,
                f"DB disk usage {pct}% ({mb} MB)",
                (
                    f"Database size {mb} MB is at {pct}% of the "
                    f"{_CAP_BYTES // 1024 // 1024} MB cap "
                    f"(>= {threshold // 1024 // 1024} MB {severity} threshold). "
                    "Prune real-time tables or upgrade the disk."
                ),
                json.dumps({
                    "alert_type": "disk_usage",
                    "bytes": bytes_used,
                    "percentage": pct,
                    "threshold_bytes": threshold,
                }),
            )
            logger.warning(
                "disk_monitor: emitted %s alert bytes=%d pct=%s", severity, bytes_used, pct,
            )
            return severity
    except Exception as exc:  # noqa: BLE001 — must never crash the scheduler
        logger.exception("disk_monitor: failed: %s", exc)
        try:
            import sentry_sdk
            sentry_sdk.capture_exception(exc)
        except Exception:  # noqa: BLE001 — Sentry optional
            pass
        return None


__all__ = ["run_job", "JOB_ID"]
