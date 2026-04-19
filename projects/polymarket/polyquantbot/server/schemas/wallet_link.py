"""Wallet-link schema foundation — user-owned external wallet address records."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

WalletLinkStatus = Literal["active", "unlinked"]
WalletLinkType = Literal["user_proxy", "external"]


class WalletLinkCreateRequest(BaseModel):
    wallet_address: str = Field(min_length=1)
    chain_id: str = Field(default="polygon", min_length=1)
    link_type: WalletLinkType = "user_proxy"


class WalletLinkRecord(BaseModel):
    link_id: str
    tenant_id: str
    user_id: str
    wallet_address: str
    chain_id: str
    link_type: WalletLinkType
    linked_at: datetime
    status: WalletLinkStatus = "active"
