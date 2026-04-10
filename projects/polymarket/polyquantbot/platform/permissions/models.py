from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PermissionProfile:
    user_id: str
    allowed_markets: tuple[str, ...]
    live_enabled: bool
    paper_enabled: bool
    max_notional_cap: float
    max_positions_cap: int
