"""
Light Portfolio Manager — Phase 2.
Selects top N trades from ranked signals.
Enforces: no duplicate market, max positions, max exposure.
No EventBus. Synchronous and deterministic.
"""

import structlog
from dataclasses import dataclass
from core.signal_model import SignalResult
from core.risk_manager import get_position_size

log = structlog.get_logger()


@dataclass
class SelectedTrade:
    signal: SignalResult
    size: float


def select_trades(
    signals: list[SignalResult],
    balance: float,
    open_market_ids: set[str],
    max_trades: int,
    max_positions: int,
    current_position_count: int,
    max_total_exposure_pct: float,
    max_position_pct: float,
) -> list[SelectedTrade]:
    """
    From ranked signals, select up to max_trades new trades.
    Constraints applied in order:
    - Skip if market already has an open position
    - Stop if position slots are full
    - Stop if cumulative exposure exceeds max_total_exposure_pct * balance
    """
    selected: list[SelectedTrade] = []
    cumulative_exposure = 0.0
    slots_available = max_positions - current_position_count

    if slots_available <= 0:
        log.info("portfolio_full", current=current_position_count, max=max_positions)
        return []

    for sig in signals:
        if len(selected) >= min(max_trades, slots_available):
            break

        if sig.market_id in open_market_ids:
            log.debug("duplicate_market_skipped", market_id=sig.market_id)
            continue

        size = get_position_size(
            balance=balance,
            ev=sig.ev,
            p_model=sig.p_model,
            p_market=sig.p_market,
            max_position_pct=max_position_pct,
        )

        if size <= 0:
            continue

        projected_exposure = (cumulative_exposure + size) / balance
        if projected_exposure > max_total_exposure_pct:
            log.debug(
                "exposure_limit_reached",
                projected=round(projected_exposure, 4),
                limit=max_total_exposure_pct,
            )
            break

        cumulative_exposure += size
        selected.append(SelectedTrade(signal=sig, size=size))
        log.info(
            "trade_selected",
            market_id=sig.market_id,
            edge_score=round(sig.edge_score, 4),
            size=size,
        )

    return selected
