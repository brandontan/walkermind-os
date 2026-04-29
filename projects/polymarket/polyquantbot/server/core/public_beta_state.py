"""Shared runtime state for public paper beta control plane and worker."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from datetime import datetime as _dt
from zoneinfo import ZoneInfo


@dataclass
class PaperPosition:
    condition_id: str
    side: str
    size: float
    entry_price: float
    edge: float
    unrealized_pnl: float = 0.0


@dataclass
class WorkerIterationSummary:
    candidate_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    skip_autotrade_count: int = 0
    skip_kill_count: int = 0
    skip_mode_count: int = 0
    current_position_count: int = 0
    risk_rejection_reasons: dict[str, int] = field(default_factory=dict)


@dataclass
class WorkerRuntimeStatus:
    active: bool = False
    startup_complete: bool = False
    shutdown_complete: bool = False
    iterations_total: int = 0
    last_iteration: WorkerIterationSummary = field(default_factory=WorkerIterationSummary)
    last_error: str = ""


@dataclass
class PublicBetaState:
    mode: str = "paper"
    autotrade_enabled: bool = False
    kill_switch: bool = False
    pnl: float = 0.0
    realized_pnl: float = 0.0
    # Baseline lifetime realized_pnl captured at day-open for day-scoped tracking.
    # Reset each Jakarta midnight via reset_daily_pnl_if_needed().
    daily_open_realized_pnl: float = 0.0
    daily_reset_date: date | None = None
    drawdown: float = 0.0
    exposure: float = 0.0
    last_risk_reason: str = ""
    wallet_cash: float = 0.0
    wallet_locked: float = 0.0
    wallet_equity: float = 0.0
    positions: list[PaperPosition] = field(default_factory=list)
    processed_signals: set[str] = field(default_factory=set)
    worker_runtime: WorkerRuntimeStatus = field(default_factory=WorkerRuntimeStatus)

    @property
    def daily_realized_pnl(self) -> float:
        """PnL realized since the last Jakarta-midnight reset.

        On first use or after any restart the baseline is initialised to the
        current lifetime total, so the day always opens at 0.0.
        """
        return round(self.realized_pnl - self.daily_open_realized_pnl, 4)

    def reset_daily_pnl_if_needed(self) -> None:
        """Snapshot today's opening baseline if the Jakarta calendar day has turned.

        Idempotent — calling multiple times on the same day is a no-op.
        """
        today: date = _dt.now(ZoneInfo("Asia/Jakarta")).date()
        if self.daily_reset_date != today:
            self.daily_open_realized_pnl = self.realized_pnl
            self.daily_reset_date = today


STATE = PublicBetaState()
