"""Non-secret live execution readiness truth for operator surfaces."""
from __future__ import annotations

from typing import Any

from ...config import get_settings


def live_readiness_truth(settings: Any | None = None) -> dict[str, Any]:
    """Return non-secret live/relayer readiness facts.

    The payload intentionally contains only booleans, enum-ish labels, and
    source names. It must never expose key material or private wallet data.
    """
    s = settings or get_settings()
    relayer_api_key_configured = bool(
        getattr(s, "USE_BUILDER_RELAYER", False)
        and getattr(s, "RELAYER_API_KEY", None)
        and getattr(s, "RELAYER_API_KEY_ADDRESS", None)
    )
    builder_configured = bool(
        getattr(s, "USE_BUILDER_RELAYER", False)
        and getattr(s, "POLY_BUILDER_API_KEY", None)
        and getattr(s, "POLY_BUILDER_SECRET", None)
        and getattr(s, "POLY_BUILDER_PASSPHRASE", None)
    )
    custody_raw = (getattr(s, "CUSTODY_MODE", "") or "").strip().lower()
    if getattr(s, "USE_PER_USER_EXECUTION", False):
        custody_mode = "deposit_wallet"
        funder_source = "per_user_deposit_wallet"
    elif custody_raw in {"eoa", "safe"}:
        custody_mode = custody_raw
        funder_source = (
            "POLYMARKET_FUNDER_ADDRESS"
            if getattr(s, "POLYMARKET_FUNDER_ADDRESS", None)
            else "signer_eoa"
        )
    else:
        custody_mode = "unknown"
        funder_source = "unknown"
    return {
        "real_clob_armed": bool(getattr(s, "USE_REAL_CLOB", False)),
        "relayer_configured": relayer_api_key_configured or builder_configured,
        "relayer_api_key_address_configured": relayer_api_key_configured,
        "builder_configured": builder_configured,
        "builder_code_configured": bool(getattr(s, "POLYMARKET_BUILDER_CODE", None)),
        "builder_address_configured": bool(
            getattr(s, "POLYMARKET_BUILDER_ADDRESS", None)
        ),
        "custody_mode": custody_mode,
        "signature_type": getattr(s, "POLYMARKET_SIGNATURE_TYPE", None),
        "funder_deposit_wallet_source": funder_source,
        "execution_path_validated": bool(
            getattr(s, "EXECUTION_PATH_VALIDATED", False)
        ),
    }
