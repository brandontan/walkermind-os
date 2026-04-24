"""Paper portfolio mutations for public beta worker."""
from __future__ import annotations

from projects.polymarket.polyquantbot.server.core.paper_account import PaperAccountState
from projects.polymarket.polyquantbot.server.core.public_beta_state import PaperPosition, PublicBetaState
from projects.polymarket.polyquantbot.server.integrations.falcon_gateway import CandidateSignal


class PaperPortfolio:
    def open_position(
        self,
        *,
        signal: CandidateSignal,
        state: PublicBetaState,
        fill_size: float,
        fill_price: float,
        account: PaperAccountState,
    ) -> PaperPosition:
        position = PaperPosition(
            condition_id=signal.condition_id,
            side=signal.side,
            size=fill_size,
            entry_price=fill_price,
            edge=signal.edge,
        )
        state.positions.append(position)
        account.apply_fill(
            condition_id=signal.condition_id,
            side=signal.side,
            fill_size=fill_size,
            fill_price=fill_price,
        )
        state.pnl = account.realized_pnl + account.unrealized_pnl
        equity = max(account.equity, 1.0)
        state.exposure = min(1.0, account.total_exposure / equity)
        state.drawdown = account.max_drawdown
        state.processed_signals.add(signal.signal_id)
        return position
