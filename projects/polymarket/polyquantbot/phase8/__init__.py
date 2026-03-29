"""Phase 8 — Hardened control system for real capital deployment.

Modules:
    risk_guard      — Kill switch authority, disabled flag, global override.
    position_tracker — Locked position state, no duplicate market_id.
    fill_monitor     — Deterministic fill tracking, retry+timeout, dedup.
    exit_monitor     — Locked exit execution, snapshot pattern, double-close guard.
    health_monitor   — Latency/fill-rate alerts, exposure consistency check.
    order_guard      — Duplicate order protection, active_orders set.

Design guarantees:
    - All state mutations are protected by asyncio.Lock.
    - Long I/O operations NEVER hold a lock (snapshot-then-process pattern).
    - risk_guard.disabled fast-path checked at the top of every control flow.
    - Kill switch sets disabled=True as its very first action.
    - Exponential backoff (2^n seconds) on all retries.
    - Zero silent failures — every error path raises or logs explicitly.
"""
from .risk_guard import RiskGuard
from .position_tracker import PositionTracker, PositionState, PositionRecord
from .fill_monitor import FillMonitor
from .exit_monitor import ExitMonitor
from .health_monitor import HealthMonitor
from .order_guard import OrderGuard

__all__ = [
    "RiskGuard",
    "PositionTracker",
    "PositionState",
    "PositionRecord",
    "FillMonitor",
    "ExitMonitor",
    "HealthMonitor",
    "OrderGuard",
]
