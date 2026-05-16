"""Pydantic schemas for all WebTrader API requests and responses."""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from pydantic import BaseModel


# ── Auth ──────────────────────────────────────────────────────────────────────

class TelegramAuthPayload(BaseModel):
    id: int
    first_name: str
    last_name: Optional[str] = None
    username: Optional[str] = None
    photo_url: Optional[str] = None
    auth_date: int
    hash: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    first_name: str


# ── Dashboard ─────────────────────────────────────────────────────────────────

class DashboardSummary(BaseModel):
    balance_usdc: float
    equity_usdc: float
    pnl_today: float
    pnl_7d: float
    open_positions: int
    total_trades: int
    wins: int
    losses: int
    auto_trade_on: bool
    kill_switch_active: bool
    trading_mode: str
    active_preset: Optional[str] = None


# ── Positions / Orders ────────────────────────────────────────────────────────

class PositionItem(BaseModel):
    id: str
    market_id: str
    market_question: Optional[str] = None
    side: str
    size_usdc: float
    entry_price: float
    current_price: Optional[float] = None
    pnl_usdc: Optional[float] = None
    status: str
    mode: str
    opened_at: datetime
    closed_at: Optional[datetime] = None


class OrderItem(BaseModel):
    id: str
    market_id: str
    side: str
    size_usdc: float
    price: float
    status: str
    mode: str
    strategy_type: Optional[str] = None
    created_at: datetime


# ── Auto-Trade ────────────────────────────────────────────────────────────────

class AutoTradeState(BaseModel):
    auto_trade_on: bool
    active_preset: Optional[str] = None
    risk_profile: str
    capital_alloc_pct: float
    tp_pct: float
    sl_pct: float


class AutoTradeToggleRequest(BaseModel):
    enabled: bool


class PresetActivateRequest(BaseModel):
    preset_key: str


class CustomizeRequest(BaseModel):
    tp_pct: Optional[float] = None
    sl_pct: Optional[float] = None
    capital_alloc_pct: Optional[float] = None
    max_position_pct: Optional[float] = None
    auto_redeem_mode: Optional[str] = None
    category_filters: Optional[list[str]] = None


# ── Wallet ────────────────────────────────────────────────────────────────────

class LedgerEntry(BaseModel):
    type: str
    amount_usdc: float
    note: Optional[str] = None
    created_at: datetime


class WalletInfo(BaseModel):
    deposit_address: str
    balance_usdc: float
    ledger_recent: list[LedgerEntry]


# ── Settings ──────────────────────────────────────────────────────────────────

class UserSettingsUpdate(BaseModel):
    risk_profile: Optional[str] = None
    notifications_on: Optional[bool] = None


# ── Alerts ───────────────────────────────────────────────────────────────────

class AlertItem(BaseModel):
    id: str
    severity: str
    title: str
    body: Optional[str] = None
    created_at: datetime


# ── Kill Switch ───────────────────────────────────────────────────────────────

class KillSwitchStatus(BaseModel):
    active: bool


# ── SSE ──────────────────────────────────────────────────────────────────────

class SSEEvent(BaseModel):
    type: str
    payload: dict
