"""Pin the polymarket SDK's on-chain reads to the operator-configured RPC.

The official ``polymarket`` SDK ships ``PRODUCTION.rpc_url`` pointed at a free
third-party endpoint (``https://polygon.drpc.org``) and uses it for the
on-chain deposit-wallet factory check inside ``AsyncSecureClient.create``.
From the Fly production machine that endpoint throttles/fails — proven
2026-06-11 when the admin deposit-wallet backfill returned
``scanned 6, filled 0, skipped 6`` (every resolve failed identically) while
the configured ``POLYGON_RPC_URL`` was healthy.

Every ``AsyncSecureClient`` built in this codebase must pass
``environment=production_environment()`` so the SDK's chain reads ride the
same operator-configured, retry-monitored RPC as the rest of the system —
never an unconfigured third-party dependency on the capital path.
"""
from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from ...config import get_settings

if TYPE_CHECKING:  # pragma: no cover - typing only
    from polymarket.environments import Environment


def production_environment() -> "Environment":
    """SDK PRODUCTION environment with ``rpc_url`` = our ``POLYGON_RPC_URL``.

    Import is deferred: environments without the ``polymarket`` SDK installed
    must not crash at module import (same posture as every SDK call site).
    """
    from polymarket.environments import PRODUCTION  # noqa: WPS433

    return dataclasses.replace(
        PRODUCTION, rpc_url=get_settings().POLYGON_RPC_URL,
    )
