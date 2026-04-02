"""UserContext — per-request scoped user identity.

Each Telegram request carries a UserContext that binds the
telegram_user_id to its assigned wallet_id.  No global state is used.

Usage::

    ctx = UserContext(telegram_user_id=123456789, wallet_id="wlt_abc123")
    # Pass ctx into every handler that touches user-scoped resources.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import time


@dataclass(frozen=True, slots=True)
class UserContext:
    """Immutable per-request user identity.

    Attributes:
        telegram_user_id: Telegram integer user ID (primary key).
        wallet_id: Assigned custodial wallet identifier.
        request_ts: Unix timestamp when this context was created.
    """

    telegram_user_id: int
    wallet_id: str
    request_ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        """Return JSON-serialisable representation."""
        return {
            "telegram_user_id": self.telegram_user_id,
            "wallet_id": self.wallet_id,
            "request_ts": self.request_ts,
        }
