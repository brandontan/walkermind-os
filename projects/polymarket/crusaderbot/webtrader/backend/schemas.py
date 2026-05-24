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
    exit_reason: Optional[str] = None


class OrderItem(BaseModel):
    id: str
    market_id: str
    market_question: Optional[str] = None
    side: str
    size_usdc: float
    price: float
    status: str
    mode: str
    strategy_type: Optional[str] = None
    filled_amount: float = 0.0
    remaining_amount: Optional[float] = None
    created_at: datetime


class ClosePositionResponse(BaseModel):
    order_id: Optional[str] = None
    estimated_fill: float
    status: str


# ── Auto-Trade ────────────────────────────────────────────────────────────────

class AutoTradeState(BaseModel):
    auto_trade_on: bool
    active_preset: Optional[str] = None
    risk_profile: str
    capital_alloc_pct: float
    tp_pct: float
    sl_pct: float
    market_categories: list[str] = []
    min_liquidity: float = 1000.0
    max_resolution_days: Optional[int] = None
    min_volume_24h: float = 100.0
    slippage_tolerance_pct: Optional[float] = None
    selected_timeframe: Optional[str] = None  # '5m' | '15m' for crypto-short presets
    selected_assets: Optional[list[str]] = None  # e.g. ['BTC','ETH'] for crypto-short presets


class AutoTradeToggleRequest(BaseModel):
    enabled: bool


class PresetActivateRequest(BaseModel):
    preset_key: str
    selected_timeframe: Optional[str] = None  # '5m' | '15m' (crypto-short presets only)
    selected_assets: Optional[list[str]] = None  # crypto-short presets only


class CustomizeRequest(BaseModel):
    tp_pct: Optional[float] = None
    sl_pct: Optional[float] = None
    capital_alloc_pct: Optional[float] = None
    max_position_pct: Optional[float] = None
    auto_redeem_mode: Optional[str] = None
    category_filters: Optional[list[str]] = None


class RiskProfileRequest(BaseModel):
    profile: str  # conservative | balanced | aggressive | custom
    capital_alloc_pct: Optional[float] = None  # required when profile='custom'
    tp_pct: Optional[float] = None             # required when profile='custom'
    sl_pct: Optional[float] = None             # required when profile='custom'


# ── Wallet ────────────────────────────────────────────────────────────────────

class LedgerEntry(BaseModel):
    id: str
    type: str
    amount_usdc: float
    note: Optional[str] = None
    created_at: datetime


class WalletInfo(BaseModel):
    deposit_address: str
    balance_usdc: float
    ledger_recent: list[LedgerEntry]
    paper_mode: bool = True
    trading_mode: str = "paper"


class LedgerPage(BaseModel):
    entries: list[LedgerEntry]
    has_more: bool
    total: int


# ── Settings ──────────────────────────────────────────────────────────────────

class UserSettingsUpdate(BaseModel):
    risk_profile: Optional[str] = None
    notifications_on: Optional[bool] = None


class TradingSettingsUpdate(BaseModel):
    auto_redeem: Optional[bool] = None
    redeem_mode: Optional[str] = None
    min_liquidity_usd: Optional[float] = None
    slippage_tolerance_pct: Optional[float] = None


class MarketFilterUpdate(BaseModel):
    market_categories: Optional[list[str]] = None
    min_liquidity: Optional[float] = None
    max_resolution_days: Optional[int] = None
    min_volume_24h: Optional[float] = None


# ── Alerts ───────────────────────────────────────────────────────────────────

class AlertItem(BaseModel):
    id: str
    severity: str
    title: str
    body: Optional[str] = None
    created_at: datetime


# ── Portfolio ─────────────────────────────────────────────────────────────────

class PortfolioSummary(BaseModel):
    available_usdc: float
    realized_pnl: float
    unrealized_pnl: float
    equity_usdc: float
    balance_usdc: float


class ChartPoint(BaseModel):
    ts: str
    equity: float


# ── Kill Switch ───────────────────────────────────────────────────────────────

class KillSwitchStatus(BaseModel):
    active: bool


# ── SSE ──────────────────────────────────────────────────────────────────────

class SSEEvent(BaseModel):
    type: str
    payload: dict


# ── Portfolio Analytics ───────────────────────────────────────────────────────

class StrategyPnl(BaseModel):
    strategy: str
    pnl_usdc: float


class TradeHighlight(BaseModel):
    market_question: Optional[str]
    pnl_usdc: float


class PortfolioAnalytics(BaseModel):
    has_data: bool
    max_drawdown_pct: Optional[float]
    profit_per_strategy: list[StrategyPnl]
    best_trade: Optional[TradeHighlight]
    worst_trade: Optional[TradeHighlight]
    win_loss_ratio: Optional[float]
    wins: int
    losses: int
    avg_hold_hours: Optional[float]


# ── Leaderboard ───────────────────────────────────────────────────────────────

class LeaderboardEntry(BaseModel):
    rank: int
    wallet: str
    alias: Optional[str]
    win_rate: Optional[float]
    total_pnl: Optional[float]
    volume_usdc: Optional[float]
    roi_pct: Optional[float]
    badge: Optional[str]


# ── Runtime Status ────────────────────────────────────────────────────────────

class RuntimeStatus(BaseModel):
    """Realtime backend runtime state for operator trust surface."""
    trading_mode: str
    paper_mode: bool
    active_preset: Optional[str]
    risk_profile: str
    kill_switch_active: bool
    open_positions: int
    scanner_scanned: int
    scanner_published: int
    scanner_last_tick: Optional[float]
