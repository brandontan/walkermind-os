"""Position-state domain layer (R12c).

Encapsulates every read/write against the ``positions`` table that the exit
watcher and order-close paths depend on. Centralising those calls here is the
defence-in-depth boundary that keeps applied_tp_pct / applied_sl_pct
immutable after entry — there is no public function in this package that
mutates them, and the DB-level trigger added in migration 005 raises if any
other code path tries.
"""
from __future__ import annotations

from .registry import (
    ExitReason,
    OpenPositionForExit,
    finalize_close_failed,
    list_open_for_exit,
    mark_force_close_intent_for_user,
    record_close_failure,
    reset_close_failure,
    update_current_price,
)

__all__ = [
    "ExitReason",
    "OpenPositionForExit",
    "finalize_close_failed",
    "list_open_for_exit",
    "mark_force_close_intent_for_user",
    "record_close_failure",
    "reset_close_failure",
    "update_current_price",
]
