"""Shared runtime state for public paper beta control plane and worker."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PaperPosition:
    position_id: str
    condition_id: str
    side: str
    size: float
    entry_price: float
    edge: float
    mark_price: float
    unrealized_pnl: float = 0.0
    status: str = "open"


@dataclass
class PaperOrder:
    order_id: str
    signal_id: str
    condition_id: str
    side: str
    requested_size: float
    filled_size: float
    requested_price: float
    fill_price: float
    status: str
    lifecycle: list[str] = field(default_factory=list)


@dataclass
class PaperAccount:
    account_id: str = "paper-default"
    cash_balance: float = 10000.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    equity: float = 10000.0
    order_count: int = 0
    reset_count: int = 0


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
    drawdown: float = 0.0
    exposure: float = 0.0
    last_risk_reason: str = ""
    paper_account: PaperAccount = field(default_factory=PaperAccount)
    positions: list[PaperPosition] = field(default_factory=list)
    orders: list[PaperOrder] = field(default_factory=list)
    processed_signals: set[str] = field(default_factory=set)
    worker_runtime: WorkerRuntimeStatus = field(default_factory=WorkerRuntimeStatus)


STATE = PublicBetaState()
