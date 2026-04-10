from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class WalletBinding:
    wallet_binding_id: str
    user_id: str
    wallet_type: str
    signature_type: str
    funder_address: str
    auth_state: str
    mode: str
    auth_provider: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class WalletContext:
    user_id: str
    wallet_binding_id: str
    wallet_type: str
    signature_type: str
    auth_state: str
    funder_address: str
    mode: str
    auth_provider: str
