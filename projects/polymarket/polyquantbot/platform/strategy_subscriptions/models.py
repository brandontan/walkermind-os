from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class StrategySubscription:
    subscription_id: str
    user_id: str
    strategy_id: str
    enabled: bool
    risk_budget: float
    created_at: datetime
    updated_at: datetime
