"""Paper execution boundary that never writes live orders."""
from __future__ import annotations

from projects.polymarket.polyquantbot.server.core.public_beta_state import PublicBetaState
from projects.polymarket.polyquantbot.server.integrations.falcon_gateway import CandidateSignal
from projects.polymarket.polyquantbot.server.portfolio.paper_portfolio import PaperPortfolio


class PaperExecutionEngine:
    def __init__(self, portfolio: PaperPortfolio) -> None:
        self._portfolio = portfolio

    async def execute(self, signal: CandidateSignal, state: PublicBetaState) -> dict[str, object]:
        """Execute a paper order via the real PaperEngine and sync STATE.

        Args:
            signal: CandidateSignal with edge, price, side, condition_id.
            state:  Live PublicBetaState — mutated in-place after execution.

        Returns:
            Dict with execution summary for the worker loop event log.
        """
        position = await self._portfolio.open_position(signal=signal, state=state)
        return {
            "mode": "paper",
            "condition_id": position.condition_id,
            "size": position.size,
            "entry_price": position.entry_price,
            "side": position.side,
            "unrealized_pnl": position.unrealized_pnl,
        }
