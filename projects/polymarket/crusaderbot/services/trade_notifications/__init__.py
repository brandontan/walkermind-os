"""Trade notification service — public API.

Exposes ``TradeNotifier`` for all paper-mode trade lifecycle events:
ENTRY, TP_HIT, SL_HIT, MANUAL, EMERGENCY, COPY_TRADE (scaffold).
"""
from .notifier import TradeNotifier, NotificationEvent

__all__ = ["TradeNotifier", "NotificationEvent"]
