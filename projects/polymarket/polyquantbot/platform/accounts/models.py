from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class UserAccount:
    """Phase 1 foundation contract for user identity mapping in legacy bridge mode."""

    user_id: str
    external_user_id: str
    source_type: str
    status: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class RiskProfileRef:
    """Reference handle for risk profile selection in future phases."""

    profile_id: str
    version: str
