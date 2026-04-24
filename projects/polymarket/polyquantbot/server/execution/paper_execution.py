"""Paper execution boundary that never writes live orders."""
from __future__ import annotations

from projects.polymarket.polyquantbot.server.core.public_beta_state import PublicBetaState
from projects.polymarket.polyquantbot.server.integrations.falcon_gateway import CandidateSignal
from projects.polymarket.polyquantbot.server.portfolio.paper_portfolio import PaperPortfolio
from projects.polymarket.polyquantbot.server.services.paper_account_service import PaperAccountService


class PaperExecutionEngine:
    def __init__(self, portfolio: PaperPortfolio, account_service: PaperAccountService) -> None:
        self._portfolio = portfolio
        self._account_service = account_service

    def execute(self, signal: CandidateSignal, state: PublicBetaState) -> dict[str, object]:
        order_id = f"paper-{signal.signal_id}"
        lifecycle = ["accepted", "filled"]
        position = self._portfolio.open_position(signal=signal, state=state)
        fill_notional = position.size * position.entry_price
        account = self._account_service.record_fill(fill_notional=fill_notional, state=state)
        return {
            "mode": "paper",
            "order_id": order_id,
            "lifecycle": lifecycle,
            "condition_id": position.condition_id,
            "size": position.size,
            "entry_price": position.entry_price,
            "side": position.side,
            "cash_balance": account.cash_balance,
            "paper_only_execution_boundary": True,
        }
