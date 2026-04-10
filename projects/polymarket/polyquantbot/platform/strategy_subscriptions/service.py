from __future__ import annotations

import uuid

from ..storage.models import StrategySubscriptionRecord, utc_now
from ..storage.repositories import StrategySubscriptionRepository
from .models import StrategySubscription


class StrategySubscriptionService:
    def __init__(self, repository: StrategySubscriptionRepository | None = None) -> None:
        self._repository = repository

    def set_subscription(
        self,
        *,
        user_id: str,
        strategy_id: str,
        enabled: bool,
        risk_budget: float = 1.0,
    ) -> StrategySubscription:
        timestamp = utc_now()
        existing = None
        for row in self.list_user_subscriptions(user_id=user_id):
            if row.strategy_id == strategy_id:
                existing = row
                break
        subscription_id = existing.subscription_id if existing else f"sub-{uuid.uuid4().hex[:10]}"
        created_at = existing.created_at if existing else timestamp
        record = StrategySubscriptionRecord(
            subscription_id=subscription_id,
            user_id=user_id,
            strategy_id=strategy_id,
            enabled=enabled,
            risk_budget=risk_budget,
            created_at=created_at,
            updated_at=timestamp,
        )
        if self._repository is not None:
            self._repository.upsert(record)
        return StrategySubscription(**record.__dict__)

    def list_user_subscriptions(self, *, user_id: str) -> tuple[StrategySubscription, ...]:
        if self._repository is None:
            return ()
        return tuple(StrategySubscription(**record.__dict__) for record in self._repository.list_by_user_id(user_id=user_id))
