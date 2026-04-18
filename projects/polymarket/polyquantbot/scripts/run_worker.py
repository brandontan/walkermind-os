"""Run the CrusaderBot worker surface placeholder."""
from __future__ import annotations

import asyncio

import structlog

log = structlog.get_logger(__name__)


async def run_worker() -> None:
    log.info(
        "crusaderbot_worker_bootstrap_ready",
        runtime="scripts.run_worker",
        status="idle",
    )
    await asyncio.sleep(0)


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
