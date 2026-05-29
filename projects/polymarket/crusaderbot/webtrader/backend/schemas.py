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


class EmailRegisterRequest(BaseModel):
    email: str
    password: str
    first_name: str


class EmailLoginRequest(BaseModel):
    email: str
    password: str


class LinkEmailRequest(BaseModel):
    email: str
    password: str


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
    risk_profile: str = "balanced"
    pnl_alltime: float = 0.0
    signals_today: int = 0


# ── Market feed ───────────────────────────────────────────────────────────────

class MarketFeedItem(BaseModel):
    """One live crypto up/down candle market for the Home market-feed ticker.

    Sourced from the already-synced ``markets`` table (Polymarket CLOB prices);
    no external spot-price dependency. ``up_prob`` is the YES (Up) probability.
    """
    asset: str
    label: str
    up_prob: float
    lean: str  # "UP" | "DOWN" | "EVEN"
    seconds_to_close: int
    liquidity_usdc: float


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
    strategy_type: Optional[str] = None
    active_preset: Optional[str] = None
    # TP/SL as configured fractions + the derived trigger price levels (in the
    # same YES-price units as entry_price/current_price). Powers the expandable
    # trade detail view. None when the position carries no TP/SL.
    tp_pct: Optional[float] = None
    sl_pct: Optional[float] = None
    tp_price: Optional[float] = None
    sl_price: Optional[float] = None
    # True when the market resolved in this position's favour but the position
    # is still open awaiting redemption (e.g. hourly auto-redeem not yet run).
    # The UI surfaces a "waiting redeem" state + a Force Redeem action.
    awaiting_redeem: bool = False


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


class EmergencyStopResponse(BaseModel):
    positions_marked: int
    user_paused: bool


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
    # Account equity (free balance + open-position value) and the resulting
    # per-trade size for the active CAP%. Surfaces in the UI so users see that
    # CAP% is the deployable pool, not the size of a single trade.
    equity_usdc: Optional[float] = None
    # The effective per-trade $ ceiling the engine will use right now (after the
    # user's max-per-trade mode is applied). This is the "Max per trade: $X".
    effective_max_per_trade_usdc: Optional[float] = None
    # The user's configured max-per-trade control (echoed back for the UI form).
    max_per_trade_mode: str = "auto"
    max_per_trade_usdc: Optional[float] = None
    max_per_trade_pct: Optional[float] = None
    # Daily loss + drawdown user overrides (stricter-only; system floors apply).
    # daily_loss_override: negative $, e.g. -300 means halt when daily PnL <= -$300.
    # max_drawdown_pct: 0–8%, e.g. 0.05 = halt at 5% drawdown (stricter than 8% system).
    daily_loss_override: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    # False when the active preset's strategy is globally disabled by the
    # operator (Ops Console on/off). The UI shows "PAUSED (Admin)" instead of
    # "ACTIVE" — no new trades fire, though the preset selection is unchanged.
    active_preset_globally_enabled: bool = True


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
    max_per_trade_mode: Optional[str] = None   # auto | fixed | pct
    max_per_trade_usdc: Optional[float] = None
    max_per_trade_pct: Optional[float] = None
    daily_loss_override: Optional[float] = None   # negative $ cap, e.g. -300
    max_drawdown_pct: Optional[float] = None      # 0 < x <= 0.08


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


class WithdrawRequest(BaseModel):
    amount_usdc: float
    destination_address: str


class WithdrawResponse(BaseModel):
    id: str
    status: str
    approval_mode: str
    amount_usdc: float


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
    total_closed: int = 0


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
    # Global operator kill switch — informational. Set ONLY by operator
    # /api/ops/kill or Telegram /kill. Webtrader users cannot toggle this.
    kill_switch_active: bool
    # Per-user paused flag (this user only). Toggled by /api/web/kill +
    # /api/web/resume and /api/web/emergency-stop. Independent of the
    # global kill switch above.
    user_paused: bool
    open_positions: int
    scanner_scanned: int
    scanner_published: int
    scanner_last_tick: Optional[float]


# ── Live-trading activation (Axis #3 — WARP/ROOT-live-activation-flow) ──────


class LiveStatus(BaseModel):
    """Per-user live-mode readiness + current state for the WebTrader UI."""
    # Current trading mode set on user_settings ("paper" | "live").
    trading_mode: str
    # Per-user live capital cap (USDC). 0 = user has not opted in.
    live_capital_cap_usdc: float
    # Aggregate USDC currently deployed across open live positions.
    open_live_exposure_usdc: float
    # Operator-level env guards — visible so the user knows whether live
    # is unlocked at the system level. ALL must be true before any user
    # can flip trading_mode='live'.
    operator_guards_open: bool
    # 8-gate live_checklist outcome (passed/failed-gates).
    checklist_passed: bool
    failed_gates: list[str]


class LiveEnableRequest(BaseModel):
    """POST /api/web/live/enable — typed-confirm flip from paper to live.

    A user must:
      1. Submit an explicit capital cap > 0 (max USDC the bot may deploy
         in live mode at any one time).
      2. Type the EXACT confirm phrase. Defends against accidental clicks
         and one-tap bots.
    """
    live_capital_cap_usdc: float
    confirm_phrase: str


class LiveEnableResponse(BaseModel):
    trading_mode: str
    live_capital_cap_usdc: float


class StrategyToggleRequest(BaseModel):
    """POST /api/web/admin/strategies/toggle — flip a strategy on/off globally."""
    name: str
    enabled: bool

