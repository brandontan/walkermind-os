"""CrusaderBot — FastAPI server entry script.

Validates required deploy environment variables before starting uvicorn.
Fails loudly (sys.exit 1) if any required variable is missing.

Usage:
    python scripts/run_api.py

Fly.io CMD equivalent:
    CMD ["python", "scripts/run_api.py"]

Required environment variables:
    DB_DSN   — PostgreSQL connection DSN (required before start)

Optional environment variables (see configs/env.example for full list):
    PORT            — TCP port (default: 8080, injected by Fly.io)
    TRADING_MODE    — PAPER | LIVE (default: PAPER)
    REDIS_URL       — Redis connection URL
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Insert repo root so absolute imports (projects.polymarket.polyquantbot.*) resolve.
# In Docker: PYTHONPATH=/workspace already set; this is a dev-mode fallback.
_repo_root = Path(__file__).resolve().parents[4]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

import structlog

log = structlog.get_logger(__name__)

_REQUIRED_ENV: list[str] = ["DB_DSN"]


def _validate_env() -> None:
    """Exit with a clear error if any required env var is missing."""
    missing = [v for v in _REQUIRED_ENV if not os.environ.get(v)]
    if missing:
        log.error(
            "crusaderbot_startup_blocked",
            missing_env=missing,
            hint="Set required environment variables before deploying to Fly.io",
        )
        print(
            f"[CrusaderBot] STARTUP BLOCKED — missing required env vars: {missing}",
            file=sys.stderr,
        )
        sys.exit(1)
    log.info(
        "crusaderbot_env_validated",
        app="CrusaderBot",
        required_env=_REQUIRED_ENV,
    )


if __name__ == "__main__":
    _validate_env()

    import uvicorn

    port = int(os.environ.get("PORT", "8080"))

    print(f"🛡️ CrusaderBot API starting on port {port}")
    log.info("crusaderbot_api_starting", port=port, app="CrusaderBot")

    uvicorn.run(
        "projects.polymarket.polyquantbot.server.main:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
        access_log=True,
    )
