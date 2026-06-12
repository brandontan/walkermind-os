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


def sdk_api_key() -> "object | None":
    """Polymarket SDK ``ApiKey`` for gasless/relayed workflows, or ``None``.

    ``AsyncSecureClient`` needs this to DEPLOY a deposit wallet for a fresh
    EOA (gasless, relayer pays): without it every resolve on an undeployed
    wallet raises ``UserInputError`` — the exact shape behind the prod
    backfill's ``scanned 6, filled 0, skipped 6``. Preference order:

    1. ``RelayerApiKey`` from RELAYER_API_KEY + RELAYER_API_KEY_ADDRESS
       (the operator's dedicated relayer key).
    2. ``BuilderApiKey`` from the POLY_BUILDER_* credential set.
    3. ``None`` — resolves still work for ALREADY-deployed wallets.
    """
    # getattr throughout: hermetic test fixtures stub Settings with partial
    # SimpleNamespaces (house pattern) — missing fields mean "unconfigured".
    s = get_settings()
    relayer_key = getattr(s, "RELAYER_API_KEY", None)
    relayer_addr = getattr(s, "RELAYER_API_KEY_ADDRESS", None)
    if relayer_key and relayer_addr:
        from polymarket.auth import RelayerApiKey  # noqa: WPS433
        return RelayerApiKey(key=relayer_key, address=relayer_addr)
    b_key = getattr(s, "POLY_BUILDER_API_KEY", None)
    b_secret = getattr(s, "POLY_BUILDER_SECRET", None)
    b_pass = getattr(s, "POLY_BUILDER_PASSPHRASE", None)
    if b_key and b_secret and b_pass:
        from polymarket.auth import BuilderApiKey  # noqa: WPS433
        return BuilderApiKey(key=b_key, secret=b_secret, passphrase=b_pass)
    return None
