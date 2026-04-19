"""Paper portfolio mutations for public beta worker."""
from __future__ import annotations

from projects.polymarket.polyquantbot.server.core.public_beta_state import PaperPosition, PublicBetaState
from projects.polymarket.polyquantbot.server.integrations.falcon_gateway import CandidateSignal


class PaperPortfolio:
    def open_position(self, signal: CandidateSignal, state: PublicBetaState) -> PaperPosition:
        position = PaperPosition(
            condition_id=signal.condition_id,
            side=signal.side,
            size=100.0,
            entry_price=signal.price,
            edge=signal.edge,
        )
        state.positions.append(position)
        state.exposure = min(1.0, state.exposure + 0.02)
        state.processed_signals.add(signal.signal_id)
        return position
