"""Paper account model and persistence boundary for public paper runtime."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class PaperOrder:
    order_id: str
    signal_id: str
    condition_id: str
    side: str
    requested_size: float
    requested_price: float
    fill_size: float = 0.0
    fill_price: float = 0.0
    status: str = "created"
    lifecycle: list[str] = field(default_factory=list)


@dataclass
class PaperPositionSnapshot:
    condition_id: str
    side: str
    size: float
    avg_entry_price: float
    mark_price: float
    unrealized_pnl: float


@dataclass
class PaperAccountState:
    account_id: str = "paper-default"
    balance: float = 10000.0
    equity: float = 10000.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    total_exposure: float = 0.0
    max_drawdown: float = 0.0
    positions: dict[str, PaperPositionSnapshot] = field(default_factory=dict)
    orders: list[PaperOrder] = field(default_factory=list)
    order_sequence: int = 0

    def next_order_id(self) -> str:
        self.order_sequence += 1
        return f"paper-order-{self.order_sequence:06d}"

    def apply_fill(
        self,
        *,
        condition_id: str,
        side: str,
        fill_size: float,
        fill_price: float,
    ) -> None:
        key = f"{condition_id}:{side}"
        existing = self.positions.get(key)
        if existing is None:
            position = PaperPositionSnapshot(
                condition_id=condition_id,
                side=side,
                size=fill_size,
                avg_entry_price=fill_price,
                mark_price=fill_price,
                unrealized_pnl=0.0,
            )
            self.positions[key] = position
        else:
            weighted_value = (existing.avg_entry_price * existing.size) + (fill_price * fill_size)
            existing.size += fill_size
            existing.avg_entry_price = weighted_value / existing.size
            existing.mark_price = fill_price
            existing.unrealized_pnl = (existing.mark_price - existing.avg_entry_price) * existing.size

        self._refresh_aggregate()

    def mark_positions(self, *, market_prices: dict[str, float]) -> None:
        for position in self.positions.values():
            market_price = market_prices.get(position.condition_id)
            if market_price is None:
                continue
            position.mark_price = market_price
            sign = 1.0 if position.side.upper() == "YES" else -1.0
            position.unrealized_pnl = (position.mark_price - position.avg_entry_price) * position.size * sign
        self._refresh_aggregate()

    def _refresh_aggregate(self) -> None:
        exposure = 0.0
        unrealized = 0.0
        for position in self.positions.values():
            exposure += abs(position.size * position.mark_price)
            unrealized += position.unrealized_pnl
        self.total_exposure = exposure
        self.unrealized_pnl = unrealized
        self.equity = self.balance + self.realized_pnl + self.unrealized_pnl
        peak = max(self.balance, self.equity)
        if peak > 0:
            self.max_drawdown = max(self.max_drawdown, (peak - self.equity) / peak)


class PaperAccountStore:
    """Deterministic local JSON persistence for paper account state only."""

    def __init__(self, storage_path: Path) -> None:
        self._storage_path = storage_path

    def load(self) -> PaperAccountState:
        if not self._storage_path.exists():
            return PaperAccountState()
        raw = json.loads(self._storage_path.read_text(encoding="utf-8"))
        state = PaperAccountState(
            account_id=str(raw.get("account_id", "paper-default")),
            balance=float(raw.get("balance", 10000.0)),
            equity=float(raw.get("equity", 10000.0)),
            realized_pnl=float(raw.get("realized_pnl", 0.0)),
            unrealized_pnl=float(raw.get("unrealized_pnl", 0.0)),
            total_exposure=float(raw.get("total_exposure", 0.0)),
            max_drawdown=float(raw.get("max_drawdown", 0.0)),
            order_sequence=int(raw.get("order_sequence", 0)),
        )
        state.positions = {
            key: PaperPositionSnapshot(**value)
            for key, value in dict(raw.get("positions", {})).items()
        }
        state.orders = [PaperOrder(**item) for item in list(raw.get("orders", []))]
        state._refresh_aggregate()
        return state

    def save(self, state: PaperAccountState) -> None:
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(state)
        self._storage_path.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")

