"""Core — SystemSnapshot: Unified system health snapshot.

Assembles a single dict describing the current system state for operator
visibility: mode, exposure, PnL, drawdown, active strategies, and system state.

Usage::

    from core.system_snapshot import SystemSnapshot, build_system_snapshot

    snapshot = build_system_snapshot(
        state_manager=state_manager,
        config_manager=config_manager,
        metrics=multi_strategy_metrics,
        allocator=capital_allocator,
        risk_guard=risk_guard,
        mode="LIVE",
    )
    # snapshot is a SystemSnapshot dataclass

Design:
    - Pure function: no side-effects, no I/O.
    - All fields have safe defaults — never raises on missing data.
    - Returns a typed dataclass with a to_dict() method.
    - Suitable for Telegram /health command and Redis state snapshot.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


# ── SystemSnapshot ────────────────────────────────────────────────────────────


@dataclass
class SystemSnapshot:
    """Unified real-time system health snapshot.

    Attributes:
        mode: Trading mode ("PAPER" | "LIVE").
        system_state: Current state ("RUNNING" | "PAUSED" | "HALTED").
        state_reason: Reason for current state.
        total_exposure_usd: Total open exposure in USD.
        total_pnl: Aggregate PnL across all strategies.
        drawdown: Current maximum drawdown fraction ∈ [0, 1].
        bankroll: Total available capital in USD.
        active_strategies: List of strategy names with non-zero weight.
        disabled_strategies: Strategies currently auto-disabled.
        suppressed_strategies: Strategies currently suppressed (low win_rate).
        per_strategy_pnl: Mapping strategy_name → total_pnl.
        per_strategy_win_rate: Mapping strategy_name → win_rate.
        per_strategy_trades: Mapping strategy_name → trades_executed count.
        total_trades: Aggregate trade count.
        total_signals: Aggregate signal count.
        risk_multiplier: Current risk multiplier setting.
        max_position: Current max position fraction.
        captured_at: Unix epoch when snapshot was assembled.
    """

    mode: str = "PAPER"
    system_state: str = "RUNNING"
    state_reason: str = ""
    total_exposure_usd: float = 0.0
    total_pnl: float = 0.0
    drawdown: float = 0.0
    bankroll: float = 0.0
    active_strategies: List[str] = field(default_factory=list)
    disabled_strategies: List[str] = field(default_factory=list)
    suppressed_strategies: List[str] = field(default_factory=list)
    per_strategy_pnl: Dict[str, float] = field(default_factory=dict)
    per_strategy_win_rate: Dict[str, float] = field(default_factory=dict)
    per_strategy_trades: Dict[str, int] = field(default_factory=dict)
    total_trades: int = 0
    total_signals: int = 0
    risk_multiplier: float = 0.25
    max_position: float = 0.10
    captured_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict of the snapshot."""
        return asdict(self)


# ── Builder ───────────────────────────────────────────────────────────────────


def build_system_snapshot(
    state_manager: Optional[Any] = None,
    config_manager: Optional[Any] = None,
    metrics: Optional[Any] = None,
    allocator: Optional[Any] = None,
    risk_guard: Optional[Any] = None,
    mode: str = "PAPER",
) -> SystemSnapshot:
    """Build a SystemSnapshot from live system components.

    All arguments are optional — missing components use safe defaults.
    No exceptions are propagated; errors are silently defaulted.

    Args:
        state_manager: SystemStateManager instance.
        config_manager: ConfigManager instance.
        metrics: MultiStrategyMetrics instance.
        allocator: DynamicCapitalAllocator instance.
        risk_guard: RiskGuard instance (for drawdown + exposure).
        mode: Trading mode string.

    Returns:
        :class:`SystemSnapshot` populated from live components.
    """
    snap = SystemSnapshot(mode=mode, captured_at=time.time())

    # ── System state ──────────────────────────────────────────────────────────
    if state_manager is not None:
        try:
            state_snap = state_manager.snapshot()
            snap.system_state = str(state_snap.get("state", "RUNNING"))
            snap.state_reason = str(state_snap.get("reason", ""))
        except Exception:
            pass

    # ── Config ────────────────────────────────────────────────────────────────
    if config_manager is not None:
        try:
            cfg = config_manager.snapshot()
            snap.risk_multiplier = float(cfg.risk_multiplier)
            snap.max_position = float(cfg.max_position)
        except Exception:
            pass

    # ── Metrics ───────────────────────────────────────────────────────────────
    if metrics is not None:
        try:
            snap.total_trades = metrics.total_trades
            snap.total_signals = metrics.total_signals
            m_snapshot = metrics.snapshot()
            total_pnl = 0.0
            for strategy_id, m_data in m_snapshot.items():
                snap.per_strategy_pnl[strategy_id] = round(
                    float(m_data.get("total_pnl", 0.0)), 4
                )
                snap.per_strategy_win_rate[strategy_id] = round(
                    float(m_data.get("win_rate", 0.0)), 4
                )
                snap.per_strategy_trades[strategy_id] = int(
                    m_data.get("trades_executed", 0)
                )
                total_pnl += float(m_data.get("total_pnl", 0.0))
            snap.total_pnl = round(total_pnl, 4)
        except Exception:
            pass

    # ── Allocator ─────────────────────────────────────────────────────────────
    if allocator is not None:
        try:
            alloc_snap = allocator.allocation_snapshot()
            snap.bankroll = float(alloc_snap.bankroll)
            snap.total_exposure_usd = float(alloc_snap.total_allocated_usd)
            snap.disabled_strategies = list(alloc_snap.disabled_strategies)
            snap.suppressed_strategies = list(alloc_snap.suppressed_strategies)
            # Active = has non-zero weight and not disabled/suppressed
            snap.active_strategies = [
                name
                for name, w in alloc_snap.strategy_weights.items()
                if w > 0.0
                and name not in alloc_snap.disabled_strategies
                and name not in alloc_snap.suppressed_strategies
            ]
        except Exception:
            pass

    # ── Risk guard (drawdown + exposure fallback) ─────────────────────────────
    if risk_guard is not None:
        try:
            snap.drawdown = float(getattr(risk_guard, "current_drawdown", 0.0))
            if snap.total_exposure_usd == 0.0:
                snap.total_exposure_usd = float(
                    getattr(risk_guard, "total_exposure_usd", 0.0)
                )
        except Exception:
            pass

    return snap
