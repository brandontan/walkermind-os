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


STATE = PublicBetaState()
