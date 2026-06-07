"""CLI migration entrypoint for the Fly.io release_command (WARP-80 RCA).

Runs :func:`crusaderbot.database.run_migrations` exactly once and exits non-zero
on failure. Wired as the Fly ``[deploy] release_command`` so migrations run in a
one-off release machine BEFORE the new app version is promoted:

  * success → the new version boots with the schema already migrated;
  * failure → the DEPLOY fails and Fly keeps the previous version serving,
    instead of the migration crash-looping the web app at boot (the failure mode
    that took prod down when migration 086 was added — `run_migrations()` was
    awaited unwrapped in the FastAPI lifespan, so a migration error killed
    uvicorn startup on every boot).

Invoked via:  python -m crusaderbot.scripts.migrate
"""
from __future__ import annotations

import asyncio

import structlog

from ..database import close_pool, run_migrations

logger = structlog.get_logger(__name__)


async def _main() -> int:
    try:
        applied = await run_migrations()
    except Exception as exc:  # noqa: BLE001 — fail-loud: non-zero exit fails the deploy
        logger.error("release_migration_failed", error=str(exc), exc_info=True)
        return 1
    finally:
        try:
            await close_pool()
        except Exception:  # noqa: BLE001 — best-effort cleanup, never mask the result
            pass
    logger.info("release_migration_complete", applied=applied, count=len(applied))
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
