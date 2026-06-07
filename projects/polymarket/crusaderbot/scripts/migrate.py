"""CLI migration entrypoint for the Fly.io release_command (WARP-80 RCA).

Runs :func:`crusaderbot.database.run_migrations` once and exits non-zero on
failure. Wired as the Fly ``[deploy] release_command`` so migrations run in a
one-off release machine BEFORE the new app version is promoted:

  * success → the new version boots with the schema already migrated;
  * failure → the DEPLOY fails and Fly keeps the previous version serving,
    instead of the migration crash-looping the web app at boot (the failure mode
    that took prod down when migration 086 was added — `run_migrations()` was
    awaited unwrapped in the FastAPI lifespan, so a migration error killed
    uvicorn startup on every boot).

Hardened (WARP-80 follow-up) after a release run failed in the DB-connect phase
with no fetchable Fly logs:
  * self-contained logging — does NOT import the web logging stack
    (``monitoring.logging`` pulls in starlette); the migration step stays
    decoupled from the HTTP app and works even in a minimal release image;
  * bounded connect RETRY with backoff — rides out a transient connection window
    (e.g. the connection pool briefly exhausted while the previous version is
    still being torn down during a deploy);
  * the failure traceback is ALSO printed raw to stderr, so a future failure is
    never invisible even if structlog or Fly's log fetch is flaky.

Invoked via:  python -m crusaderbot.scripts.migrate
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import traceback

import structlog

from ..database import close_pool, run_migrations

logger = structlog.get_logger(__name__)

# Bounded retry for the DB-connect phase. ~2+4+8+16+30 ≈ 60s worst case before
# the deploy is failed — long enough to ride out a connection-contention window,
# short enough to fail loud quickly on a genuine misconfiguration.
_MAX_ATTEMPTS: int = 5
_BASE_DELAY_SEC: float = 2.0
_MAX_DELAY_SEC: float = 30.0


def _configure_logging() -> None:
    """Minimal JSON logging for the release machine, decoupled from the web app.

    Deliberately avoids ``monitoring.logging.configure_json_logging`` because that
    module imports the starlette HTTP middleware — the migration step must not
    depend on the web stack. Sets stdlib + structlog to emit JSON to stdout.
    """
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(level=level, stream=sys.stdout, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )


async def _run_with_retry() -> list[str]:
    """Run migrations, retrying the connect/setup phase on transient failure."""
    last_exc: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            return await run_migrations()
        except Exception as exc:  # noqa: BLE001 — retry then re-raise loud
            last_exc = exc
            logger.warning(
                "release_migration_attempt_failed",
                attempt=attempt, max_attempts=_MAX_ATTEMPTS, error=str(exc),
            )
            # Drop any half-built pool so the next attempt reconnects cleanly.
            try:
                await close_pool()
            except Exception:  # noqa: BLE001
                pass
            if attempt < _MAX_ATTEMPTS:
                await asyncio.sleep(min(_BASE_DELAY_SEC * 2 ** (attempt - 1), _MAX_DELAY_SEC))
    assert last_exc is not None
    raise last_exc


async def _main() -> int:
    try:
        applied = await _run_with_retry()
    except Exception as exc:  # noqa: BLE001 — fail-loud: non-zero exit fails the deploy
        logger.error("release_migration_failed", error=str(exc), exc_info=True)
        # Guaranteed-visible raw traceback even if structlog / Fly log fetch is flaky.
        traceback.print_exc()
        return 1
    finally:
        try:
            await close_pool()
        except Exception:  # noqa: BLE001 — best-effort cleanup, never mask the result
            pass
    logger.info("release_migration_complete", applied=applied, count=len(applied))
    return 0


def main() -> None:
    _configure_logging()
    raise SystemExit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
