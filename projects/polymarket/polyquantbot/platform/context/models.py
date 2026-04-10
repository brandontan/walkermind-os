from __future__ import annotations

from dataclasses import dataclass

from ..accounts.models import RiskProfileRef, UserAccount
from ..permissions.models import PermissionProfile
from ..strategy_subscriptions.models import StrategySubscription
from ..wallet_auth.models import WalletContext


@dataclass(frozen=True)
class ExecutionContext:
    user_id: str
    wallet_binding_id: str
    mode: str
    allowed_markets: tuple[str, ...]
    permission_version: str
    risk_profile_ref: RiskProfileRef
    trace_id: str


@dataclass(frozen=True)
class PlatformContextEnvelope:
    user_account: UserAccount
    wallet_context: WalletContext
    permission_profile: PermissionProfile
    execution_context: ExecutionContext
    strategy_subscriptions: tuple[StrategySubscription, ...] = ()
