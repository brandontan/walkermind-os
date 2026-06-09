"""Polymarket Builder relayer client wrapper (gasless capital ops, Phase 1).

Foundation only — wires the SDK behind feature flags but is NOT consumed by
any active path yet. The withdraw / sweep / redeem paths still use the EOA
master-funded model that shipped in PRs #1402 / #1403; this module exists so
the upcoming custody-migration phases (Safe deploy → SafeCustody → cutover)
have a single, tested integration surface to call.

Activation
==========
Three secrets, issued at polymarket.com/settings?tab=builder, must be set
before any relayer call works:
  * POLY_BUILDER_API_KEY
  * POLY_BUILDER_SECRET
  * POLY_BUILDER_PASSPHRASE
Plus the master toggle ``USE_BUILDER_RELAYER`` must be True. With any of those
missing, ``is_relayer_configured()`` returns False and ``make_relayer_client``
raises ``BuilderRelayerUnavailable`` — callers never silently fall back.

Why a wrapper
=============
* Soft-imports the SDK so a fresh boot without the package never crashes the
  bot (mirrors how integrations/clob/__init__.py handles py-clob-client).
* Centralises credential handling so every consumer goes through one audited
  factory — no scattered direct constructions of ``RelayClient``.
* Returns a typed error rather than a generic ``RuntimeError`` so call sites
  can distinguish "relayer unavailable" from "relayer call failed".
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from ..config import get_settings

logger = logging.getLogger(__name__)


class BuilderRelayerUnavailable(RuntimeError):
    """Raised when the relayer is asked for but credentials/flags are absent.

    Distinct from a relayer call failure: this means the relayer was never
    configured in this environment, so the caller is free to skip or fall back.
    """


def is_relayer_configured() -> bool:
    """True iff every credential is set AND the master toggle is enabled."""
    s = get_settings()
    return bool(
        s.USE_BUILDER_RELAYER
        and s.POLY_BUILDER_API_KEY
        and s.POLY_BUILDER_SECRET
        and s.POLY_BUILDER_PASSPHRASE
    )


def build_builder_config() -> Any:
    """Construct a ``BuilderConfig`` from settings, or raise if unconfigured.

    Returns ``Any`` to avoid forcing the SDK import on every module that just
    type-checks against this function.
    """
    if not is_relayer_configured():
        raise BuilderRelayerUnavailable(
            "Builder relayer unavailable: set POLY_BUILDER_API_KEY / SECRET / "
            "PASSPHRASE and USE_BUILDER_RELAYER=true to enable."
        )
    try:
        from py_builder_signing_sdk.config import BuilderConfig
        from py_builder_signing_sdk.sdk_types import BuilderApiKeyCreds
    except Exception as exc:
        raise BuilderRelayerUnavailable(
            f"py-builder-signing-sdk not installed or import failed: {exc}"
        ) from exc

    s = get_settings()
    creds = BuilderApiKeyCreds(
        key=s.POLY_BUILDER_API_KEY,
        secret=s.POLY_BUILDER_SECRET,
        passphrase=s.POLY_BUILDER_PASSPHRASE,
    )
    return BuilderConfig(local_builder_creds=creds)


def make_relayer_client(signer_pk: str) -> Any:
    """Construct a RelayClient bound to the given signer key. Polygon mainnet.

    The signer key is the EOA that controls the Safe being driven (master or
    per-user). Returns ``Any`` for the same import-decoupling reason as
    ``build_builder_config``.
    """
    if not signer_pk:
        raise BuilderRelayerUnavailable("relayer signer key is empty")
    builder_config = build_builder_config()  # raises if not configured
    try:
        from py_builder_relayer_client.client import RelayClient
    except Exception as exc:
        raise BuilderRelayerUnavailable(
            f"py-builder-relayer-client not installed or import failed: {exc}"
        ) from exc

    s = get_settings()
    return RelayClient(
        s.POLY_RELAYER_URL,
        137,
        signer_pk,
        builder_config,
    )


# Optional dependency probe used by health checks / readiness; never raises.
def relayer_sdk_importable() -> bool:
    """Cheap availability check that does NOT require credentials."""
    try:
        import py_builder_relayer_client  # noqa: F401
        import py_builder_signing_sdk  # noqa: F401
    except Exception:
        return False
    return True
