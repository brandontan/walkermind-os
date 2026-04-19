"""Shared runtime state for public paper beta control plane and worker."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PaperPosition:
    condition_id: str
    side: str
    size: float
    entry_price: float
    edge: float


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
    positions: list[PaperPosition] = field(default_factory=list)
    processed_signals: set[str] = field(default_factory=set)
    worker_runtime: WorkerRuntimeStatus = field(default_factory=WorkerRuntimeStatus)


STATE = PublicBetaState()
