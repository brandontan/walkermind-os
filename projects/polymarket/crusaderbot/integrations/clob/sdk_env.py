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
import logging
from typing import TYPE_CHECKING

from ...config import get_settings

if TYPE_CHECKING:  # pragma: no cover - typing only
    from polymarket.environments import Environment

logger = logging.getLogger(__name__)

# Families already warned about this process — sdk_api_key() runs on every
# AsyncSecureClient build, so partial-config warnings are deduped to one line
# per family instead of one per client.
_PARTIAL_WARNED: set[str] = set()


def _warn_partial_config(family: str, fields: dict[str, "object | None"]) -> None:
    """One WARNING per process when a credential family is half-configured.

    A partially-set family silently loses the preference race (Gemini #1778):
    the operator believes the key is active while every gasless deploy quietly
    falls through to the next family. Raising here would be worse — this runs
    on EVERY client build, including resolves of already-deployed wallets that
    need no key at all — so the contract is: warn loudly, keep the fallback.
    Field NAMES only; never values.
    """
    if family in _PARTIAL_WARNED:
        return
    _PARTIAL_WARNED.add(family)
    logger.warning(
        "sdk_api_key: %s credentials PARTIALLY configured — set: %s; missing: %s. "
        "Family skipped, falling back. Configure the full set or clear it.",
        family,
        ", ".join(k for k, v in fields.items() if v) or "none",
        ", ".join(k for k, v in fields.items() if not v),
    )


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

    1. ``BuilderApiKey`` from the POLY_BUILDER_* credential set. A builder
       key relays on behalf of ARBITRARY user EOAs (builder pays gas) — the
       only key kind that can deploy deposit wallets for our per-user HD
       addresses.
    2. ``RelayerApiKey`` from RELAYER_API_KEY + RELAYER_API_KEY_ADDRESS.
       Address-BOUND: the relayer only accepts requests whose ``from`` equals
       the key's own address — prod-proven 2026-06-12 when relayer-first
       selection failed all 6 backfill resolves with
       ``from 0x<user EOA> does not match auth 0x<relayer address>``.
    3. ``None`` — resolves still work for ALREADY-deployed wallets.
    """
    # getattr throughout: hermetic test fixtures stub Settings with partial
    # SimpleNamespaces (house pattern) — missing fields mean "unconfigured".
    s = get_settings()
    builder = {
        "POLY_BUILDER_API_KEY": getattr(s, "POLY_BUILDER_API_KEY", None),
        "POLY_BUILDER_SECRET": getattr(s, "POLY_BUILDER_SECRET", None),
        "POLY_BUILDER_PASSPHRASE": getattr(s, "POLY_BUILDER_PASSPHRASE", None),
    }
    if all(builder.values()):
        from polymarket.auth import BuilderApiKey  # noqa: WPS433
        return BuilderApiKey(
            key=builder["POLY_BUILDER_API_KEY"],
            secret=builder["POLY_BUILDER_SECRET"],
            passphrase=builder["POLY_BUILDER_PASSPHRASE"],
        )
    if any(builder.values()):
        _warn_partial_config("builder", builder)
    relayer = {
        "RELAYER_API_KEY": getattr(s, "RELAYER_API_KEY", None),
        "RELAYER_API_KEY_ADDRESS": getattr(s, "RELAYER_API_KEY_ADDRESS", None),
    }
    if all(relayer.values()):
        from polymarket.auth import RelayerApiKey  # noqa: WPS433
        return RelayerApiKey(
            key=relayer["RELAYER_API_KEY"],
            address=relayer["RELAYER_API_KEY_ADDRESS"],
        )
    if any(relayer.values()):
        _warn_partial_config("relayer", relayer)
    return None
