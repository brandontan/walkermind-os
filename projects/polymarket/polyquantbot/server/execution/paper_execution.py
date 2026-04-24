"""Paper execution boundary that never writes live orders."""
from __future__ import annotations

from projects.polymarket.polyquantbot.server.core.public_beta_state import PaperOrder, PublicBetaState
from projects.polymarket.polyquantbot.server.integrations.falcon_gateway import CandidateSignal
from projects.polymarket.polyquantbot.server.portfolio.paper_portfolio import PaperPortfolio


class PaperExecutionEngine:
    def __init__(self, portfolio: PaperPortfolio) -> None:
        self._portfolio = portfolio

    def execute(self, signal: CandidateSignal, state: PublicBetaState) -> dict[str, object]:
        order_index = state.paper_account.order_count + 1
        order_id = f"paper-ord-{order_index}"
        requested_size = 100.0
        fill_ratio = self._deterministic_fill_ratio(signal=signal)
        filled_size = round(requested_size * fill_ratio, 4)
        fill_price = round(signal.price + self._deterministic_slippage(signal=signal), 4)
        lifecycle = ["created", "accepted", "filled"]
        position = self._portfolio.open_position(
            signal=signal,
            state=state,
            fill_size=filled_size,
            fill_price=fill_price,
        )
        state.paper_account.order_count = order_index
        state.orders.append(
            PaperOrder(
                order_id=order_id,
                signal_id=signal.signal_id,
                condition_id=signal.condition_id,
                side=signal.side,
                requested_size=requested_size,
                filled_size=filled_size,
                requested_price=signal.price,
                fill_price=fill_price,
                status="filled",
                lifecycle=lifecycle,
            )
        )
        return {
            "mode": "paper",
            "order_id": order_id,
            "order_status": "filled",
            "lifecycle": lifecycle,
            "condition_id": position.condition_id,
            "size": position.size,
            "entry_price": position.entry_price,
            "side": position.side,
        }

    def _deterministic_fill_ratio(self, signal: CandidateSignal) -> float:
        base = 0.6 + min(max(signal.edge, 0.0), 0.2)
        return min(1.0, round(base, 4))

    def _deterministic_slippage(self, signal: CandidateSignal) -> float:
        if signal.side.upper() == "YES":
            return round(min(0.01, signal.edge * 0.1), 4)
        return round(max(-0.01, -signal.edge * 0.1), 4)
