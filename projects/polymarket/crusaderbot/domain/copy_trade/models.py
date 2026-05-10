"""Domain model for Phase 5E Copy Trade tasks."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True)
class CopyTradeTask:
    id: UUID
    user_id: UUID
    wallet_address: str
    task_name: str
    status: str          # 'paused' | 'active' | 'stopped'
    copy_mode: str       # 'fixed' | 'proportional'
    copy_amount: Decimal
    copy_pct: Decimal | None
    tp_pct: Decimal
    sl_pct: Decimal
    max_daily_spend: Decimal
    slippage_pct: Decimal
    min_trade_size: Decimal
    reverse_copy: bool
    created_at: datetime
    updated_at: datetime

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    @property
    def status_badge(self) -> str:
        return {"active": "🟢", "paused": "⏸", "stopped": "🔴"}.get(self.status, "❓")
