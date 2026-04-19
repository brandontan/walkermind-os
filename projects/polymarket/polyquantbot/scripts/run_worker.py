"""Run the CrusaderBot paper auto-trading worker."""
from __future__ import annotations

import asyncio
import os

from projects.polymarket.polyquantbot.server.workers.paper_beta_worker import run_worker_loop


async def run_worker() -> None:
    iterations = int(os.getenv("WORKER_ITERATIONS", "1"))
    await run_worker_loop(iterations=iterations)


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
