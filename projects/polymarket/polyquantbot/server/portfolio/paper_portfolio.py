"""Paper portfolio mutations for public beta worker."""
from __future__ import annotations

from projects.polymarket.polyquantbot.server.core.public_beta_state import PaperPosition, PublicBetaState
from projects.polymarket.polyquantbot.server.integrations.falcon_gateway import CandidateSignal


class PaperPortfolio:
    def open_position(
        self,
        signal: CandidateSignal,
        state: PublicBetaState,
        *,
        fill_size: float,
        fill_price: float,
    ) -> PaperPosition:
        next_position_index = len(state.positions) + 1
        position = PaperPosition(
            position_id=f"paper-pos-{next_position_index}",
            condition_id=signal.condition_id,
            side=signal.side,
            size=fill_size,
            entry_price=fill_price,
            edge=signal.edge,
            mark_price=signal.price,
        )
        state.positions.append(position)
        notional = fill_size * fill_price
        state.paper_account.cash_balance = max(0.0, state.paper_account.cash_balance - notional)
        state.exposure = min(1.0, state.exposure + (notional / max(state.paper_account.equity, 1.0)))
        state.paper_account.unrealized_pnl = self.calculate_unrealized_pnl(state=state)
        state.paper_account.equity = (
            state.paper_account.cash_balance + state.paper_account.realized_pnl + state.paper_account.unrealized_pnl
        )
        state.pnl = state.paper_account.realized_pnl + state.paper_account.unrealized_pnl
        state.processed_signals.add(signal.signal_id)
        return position

    def calculate_unrealized_pnl(self, state: PublicBetaState) -> float:
        total = 0.0
        for position in state.positions:
            if position.status != "open":
                continue
            direction = 1.0 if position.side.upper() == "YES" else -1.0
            total += (position.mark_price - position.entry_price) * position.size * direction
        return round(total, 4)
