"""Paper-account service for paper-only execution/account summaries."""
from __future__ import annotations

from projects.polymarket.polyquantbot.server.core.public_beta_state import PaperAccount, PublicBetaState
from projects.polymarket.polyquantbot.server.storage.paper_account_store import PaperAccountStore


class PaperAccountService:
    def __init__(self, store: PaperAccountStore) -> None:
        self._store = store

    def load_into_state(self, state: PublicBetaState) -> PaperAccount:
        account = self._store.get_account()
        state.paper_account = account
        state.pnl = account.realized_pnl + account.unrealized_pnl
        return account

    def record_fill(self, *, fill_notional: float, state: PublicBetaState) -> PaperAccount:
        account = state.paper_account
        account.cash_balance = max(0.0, account.cash_balance - fill_notional)
        account.daily_trade_count += 1
        account.unrealized_pnl = sum(
            (position.entry_price - 0.5) * position.size for position in state.positions
        )
        state.pnl = account.realized_pnl + account.unrealized_pnl
        self._store.put_account(account)
        return account

    def get_portfolio_summary(self, state: PublicBetaState) -> dict[str, object]:
        account = state.paper_account
        equity = account.cash_balance + account.unrealized_pnl + account.realized_pnl
        return {
            "account": {
                "account_id": account.account_id,
                "starting_balance": account.starting_balance,
                "cash_balance": account.cash_balance,
                "equity": equity,
                "realized_pnl": account.realized_pnl,
                "unrealized_pnl": account.unrealized_pnl,
                "daily_realized_pnl": account.daily_realized_pnl,
                "daily_trade_count": account.daily_trade_count,
            },
            "positions": [position.__dict__ for position in state.positions],
            "position_count": len(state.positions),
            "paper_only_execution_boundary": True,
        }
