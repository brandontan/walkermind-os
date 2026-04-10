from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


ALLOWED_ACCOUNT_MODES: set[str] = {"paper", "live_shadow", "live"}


class AccountRuntimeResolutionError(RuntimeError):
    """Raised when account runtime context is missing or invalid."""


@dataclass(frozen=True)
class WalletAuthMetadata:
    wallet_type: str | None
    wallet_address: str | None
    proxy_wallet_address: str | None
    funder_address: str | None
    credential_reference: str | None


@dataclass(frozen=True)
class AccountRuntimeEnvelope:
    user_id: str
    trading_account_id: str
    mode: str
    risk_profile: dict[str, Any]
    wallet_auth: WalletAuthMetadata


class AccountRuntimeRepository(Protocol):
    async def resolve_account_runtime_row(
        self,
        *,
        user_id: str,
        trading_account_id: str | None,
    ) -> dict[str, Any] | None:
        ...

    async def insert_trade_intent(self, payload: dict[str, Any]) -> bool:
        ...


class AccountRuntimeResolver:
    """Resolve active account + mode envelope and fail closed on invalid state."""

    def __init__(self, repository: AccountRuntimeRepository) -> None:
        self._repository = repository

    async def resolve_active_envelope(
        self,
        *,
        user_id: str,
        trading_account_id: str | None = None,
    ) -> AccountRuntimeEnvelope:
        row = await self._repository.resolve_account_runtime_row(
            user_id=user_id,
            trading_account_id=trading_account_id,
        )
        if row is None:
            raise AccountRuntimeResolutionError("account_not_found")

        mode = str(row.get("mode", "")).strip().lower()
        if mode not in ALLOWED_ACCOUNT_MODES:
            raise AccountRuntimeResolutionError("invalid_account_mode")

        wallet_auth = WalletAuthMetadata(
            wallet_type=_normalize_optional_text(row.get("wallet_type")),
            wallet_address=_normalize_optional_text(row.get("wallet_address")),
            proxy_wallet_address=_normalize_optional_text(row.get("proxy_wallet_address")),
            funder_address=_normalize_optional_text(row.get("funder_address")),
            credential_reference=_normalize_optional_text(row.get("credential_reference")),
        )
        if mode == "live" and not wallet_auth.credential_reference:
            raise AccountRuntimeResolutionError("missing_live_auth_metadata")

        raw_profile = row.get("risk_profile")
        risk_profile = raw_profile if isinstance(raw_profile, dict) else {}
        if not risk_profile:
            raise AccountRuntimeResolutionError("risk_profile_not_bound")

        return AccountRuntimeEnvelope(
            user_id=str(row.get("user_id", user_id)),
            trading_account_id=str(row.get("trading_account_id", "")),
            mode=mode,
            risk_profile=risk_profile,
            wallet_auth=wallet_auth,
        )


class TradeIntentWriter:
    """Persistence boundary for strategy decisions (not execution truth)."""

    def __init__(self, repository: AccountRuntimeRepository) -> None:
        self._repository = repository

    async def write(self, *, payload: dict[str, Any]) -> bool:
        return await self._repository.insert_trade_intent(payload)


def _normalize_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
