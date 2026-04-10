from __future__ import annotations

from dataclasses import dataclass

from ..accounts.models import RiskProfileRef
from ..accounts.service import AccountService
from ..permissions.service import PermissionService
from ..strategy_subscriptions.service import StrategySubscriptionService
from ..wallet_auth.service import WalletAuthService
from .models import ExecutionContext, PlatformContextEnvelope


@dataclass
class LegacySessionSeed:
    user_id: str
    external_user_id: str
    mode: str
    wallet_binding_id: str
    wallet_type: str
    signature_type: str
    funder_address: str
    auth_state: str
    allowed_markets: tuple[str, ...]
    trace_id: str


class ContextResolver:
    """Composes platform context contracts from legacy identifiers.
    PURE: no side-effects.
    """

    def __init__(
        self,
        account_service: AccountService | None = None,
        wallet_auth_service: WalletAuthService | None = None,
        permission_service: PermissionService | None = None,
        strategy_subscription_service: StrategySubscriptionService | None = None,
    ) => None:
        self._account_service = account_service or AccountService()
        self._wallet_auth_service = wallet_auth_service or WalletAuthService()
        self._permission_service = permission_service or PermissionService()
        self._strategy_subscription_service = strategy_subscription_service or StrategySubscriptionService()

    def resolve(self, seed: LegacySessionSeed) -> PlatformContextEnvelope:
        user_account = self._account_service.resolve_user_account(
            legacy_user_id=seed.user_id,
            source_type="legacy-session",
        )
        wallet_binding = self._wallet_auth_service.resolve_wallet_binding(
            user_id=user_account.user_id,
            wallet_binding_id=seed.wallet_binding_id,
            wallet_type=seed.wallet_type,
            signature_type=seed.signature_type,
            funder_address=seed.funder_address,
            auth_state=seed.auth_state,
            mode=seed.mode,
        )
        wallet_context = self._wallet_auth_service.to_wallet_context(wallet_binding)
        permission_profile = self._permission_service.resolve_permission_profile(
            user_id=user_account.user_id,
            allowed_markets=seed.allowed_markets,
            mode=seed.mode,
        )
        execution_context = ExecutionContext(
            user_id=user_account.user_id,
            wallet_binding_id=wallet_binding.wallet_binding_id,
            mode=seed.mode,
            allowed_markets=permission_profile.allowed_markets,
            permission_version=permission_profile.version,
            risk_profile_ref=RiskProfileRef(profile_id="legacy-default", version="v1"),
            trace_id=seed.trace_id,
        )
        strategy_subscriptions = self._strategy_subscription_service.list_user_subscriptions(user_id=user_account.user_id)
        return PlatformContextEnvelope(
            user_account=user_account,
            wallet_context=wallet_context,
            permission_profile=permission_profile,
            execution_context=execution_context,
            strategy_subscriptions=strategy_subscriptions,
        )
