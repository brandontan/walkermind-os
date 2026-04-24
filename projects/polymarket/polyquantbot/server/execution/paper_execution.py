"""Paper execution boundary that never writes live orders."""
from __future__ import annotations

from projects.polymarket.polyquantbot.server.core.paper_account import PaperOrder
from projects.polymarket.polyquantbot.server.core.public_beta_state import PublicBetaState
from projects.polymarket.polyquantbot.server.integrations.falcon_gateway import CandidateSignal
from projects.polymarket.polyquantbot.server.portfolio.paper_portfolio import PaperPortfolio


class PaperExecutionEngine:
    def __init__(self, portfolio: PaperPortfolio) -> None:
        self._portfolio = portfolio

    def execute(self, signal: CandidateSignal, state: PublicBetaState) -> dict[str, object]:
        account = state.paper_account
        order = PaperOrder(
            order_id=account.next_order_id(),
            signal_id=signal.signal_id,
            condition_id=signal.condition_id,
            side=signal.side,
            requested_size=100.0,
            requested_price=signal.price,
        )
        order.lifecycle = ["created", "validated", "submitted", "filled"]
        order.status = "filled"
        order.fill_size = round(order.requested_size * 0.9, 2)
        order.fill_price = round(signal.price, 6)
        account.orders.append(order)
        position = self._portfolio.open_position(
            signal=signal,
            state=state,
            fill_size=order.fill_size,
            fill_price=order.fill_price,
            account=account,
        )
        return {
            "mode": "paper",
            "order_id": order.order_id,
            "order_status": order.status,
            "lifecycle": list(order.lifecycle),
            "condition_id": position.condition_id,
            "size": position.size,
            "entry_price": position.entry_price,
            "side": position.side,
        }
