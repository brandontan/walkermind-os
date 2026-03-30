"""Phase 9 — Production Orchestrator.

Integrates Phase 6.6 (decision), Phase 7 (live execution), and Phase 8
(risk/control) into a single production-grade orchestrator.

Modules:
    main              — Async orchestrator entrypoint and lifecycle manager.
    decision_callback — Decision → execution bridge (strategy → sentinel → executor).
    telegram_live     — Real-time Telegram alert system (OPEN/CLOSE/KILL/etc.).
    metrics_validator — Post-run metrics computation and JSON output.

Usage::

    python -m phase9.main --config phase9/paper_run_config.yaml

Done criteria:
    - Full async pipeline runs end-to-end.
    - Paper trades executed and logged.
    - Position lifecycle (open/close) tracked correctly.
    - Kill switch disables trading immediately.
    - System stable for continuous runtime (no crashes).
    - Metrics generated after run.
    - All modules respect risk_guard.disabled.
    - Telegram alerts functioning.
"""

from .decision_callback import DecisionCallback, DecisionInput, DecisionOutput
from .metrics_validator import MetricsValidator
from .telegram_live import TelegramLive

__all__ = [
    "DecisionCallback",
    "DecisionInput",
    "DecisionOutput",
    "MetricsValidator",
    "TelegramLive",
]
