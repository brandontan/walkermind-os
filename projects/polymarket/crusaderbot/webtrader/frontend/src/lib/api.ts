const BASE = "/api/web";

// Fired when the server returns 401 — clears persisted auth so the next
// render redirects to the login page instead of looping on expired tokens.
let _onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(fn: () => void): void {
  _onUnauthorized = fn;
}

async function request<T>(
  path: string,
  token: string | null,
  opts: RequestInit = {}
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
  const res = await fetch(`${BASE}${path}`, { ...opts, headers });
  if (!res.ok) {
    if (res.status === 401) {
      _onUnauthorized?.();
    }
    const text = await res.text().catch(() => "unknown error");
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

// ── Unauthenticated auth calls ────────────────────────────────────────────────

export interface TokenResponse {
  access_token: string;
  user_id: string;
  first_name: string;
}

export async function apiRegisterEmail(
  email: string, password: string, first_name: string,
): Promise<TokenResponse> {
  return request<TokenResponse>("/auth/register", null, {
    method: "POST",
    body: JSON.stringify({ email, password, first_name }),
  });
}

export async function apiLoginEmail(
  email: string, password: string,
): Promise<TokenResponse> {
  return request<TokenResponse>("/auth/login", null, {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function makeApi(token: string | null) {
  const get = <T>(path: string) => request<T>(path, token);
  const post = <T>(path: string, body?: unknown) =>
    request<T>(path, token, { method: "POST", body: body ? JSON.stringify(body) : undefined });
  const patch = <T>(path: string, body?: unknown) =>
    request<T>(path, token, { method: "PATCH", body: body ? JSON.stringify(body) : undefined });

  return {
    getRuntimeStatus: () => get<RuntimeStatus>("/status"),
    getDashboard: () => get<DashboardSummary>("/dashboard"),
    getPositions: (status?: string, limit?: number, offset?: number) => {
      const params = new URLSearchParams();
      if (status) params.set("status", status);
      if (limit) params.set("limit", String(limit));
      if (offset) params.set("offset", String(offset));
      const qs = params.toString();
      return get<PositionItem[]>(`/positions${qs ? `?${qs}` : ""}`);
    },
    forceRedeem: (positionId: string) =>
      post<{ status: string; position_id: string }>(`/positions/${positionId}/redeem`),
    getMarketFeed: () => get<MarketFeedItem[]>("/market-feed"),
    getPortfolioSummary: () => get<PortfolioSummary>("/portfolio/summary"),
    getPortfolioChart: (period: string) =>
      get<ChartPoint[]>(`/portfolio/chart?period=${encodeURIComponent(period)}`),
    getAutotrade: () => get<AutoTradeState>("/autotrade"),
    toggleAutotrade: (enabled: boolean) => post<{ auto_trade_on: boolean }>("/autotrade/toggle", { enabled }),
    activatePreset: (preset_key: string, selected_timeframe?: "5m" | "15m", selected_assets?: string[]) =>
      post<{ active_preset: string; selected_timeframe: string | null; selected_assets: string[] | null }>(
        "/autotrade/preset", { preset_key, selected_timeframe, selected_assets }),
    setRiskProfile: (params: RiskProfileParams) => patch<{ risk_profile: string }>("/autotrade/risk-profile", params),
    customizeStrategy: (params: CustomizeParams) => post<{ updated: boolean }>("/autotrade/customize", params),
    getWallet: () => get<WalletInfo>("/wallet"),
    getLedger: (offset: number, limit = 20) =>
      get<LedgerPage>(`/wallet/ledger?offset=${offset}&limit=${limit}`),
    getSettings: () => get<UserSettings>("/settings"),
    updateSettings: (data: Partial<UserSettings>) => patch<{ updated: boolean }>("/settings", data),
    linkEmail: (email: string, password: string) =>
      post<{ ok: boolean }>("/auth/link-email", { email, password }),
    getAlerts: () => get<AlertItem[]>("/alerts"),
    getKillSwitch: () => get<{ active: boolean }>("/killswitch"),
    postKill: () => post<{ ok: boolean }>("/kill"),
    listCopyTasks: () => get<CopyTask[]>("/copy-trade/tasks"),
    createCopyTask: (body: CopyTaskCreate) =>
      post<{ id: string; status: string }>("/copy-trade/tasks", body),
    updateCopyTask: (id: string, body: CopyTaskPatch) =>
      patch<{ updated: boolean }>(`/copy-trade/tasks/${id}`, body),
    deleteCopyTask: (id: string) =>
      request<void>(`/copy-trade/tasks/${id}`, token, { method: "DELETE" }),
    getCopyTaskStats: (id: string) =>
      get<Record<string, unknown>>(`/copy-trade/tasks/${id}/stats`),
    updateTradingSettings: (data: TradingSettings) =>
      patch<{ updated: boolean }>("/config/trading", data),
    updateMarketFilters: (data: MarketFilterSettings) =>
      patch<{ updated: boolean }>("/autotrade/market-filters", data),
    getOrders: (limit?: number, offset?: number) => {
      const params = new URLSearchParams();
      if (limit) params.set("limit", String(limit));
      if (offset) params.set("offset", String(offset));
      const qs = params.toString();
      return get<OrderItem[]>(`/orders${qs ? `?${qs}` : ""}`);
    },
    closePosition: (positionId: string) =>
      post<ClosePositionResult>(`/positions/${positionId}/close`),
    getPortfolioAnalytics: () => get<PortfolioAnalytics>("/portfolio/analytics"),
    getLeaderboard: (offset = 0, limit = 10) =>
      get<LeaderboardEntry[]>(`/leaderboard?offset=${offset}&limit=${limit}`),
    getWallet360: (address: string) =>
      get<Wallet360>(`/copy-trade/wallet-360/${address}`),
    getRecentSignals: (limit = 10, offset = 0) =>
      get<FeedSignal[]>(`/signals/recent?limit=${limit}&offset=${offset}`),
  };
}

// ── Types mirroring backend schemas ──────────────────────────────────────────

export interface DashboardSummary {
  balance_usdc: number;
  equity_usdc: number;
  pnl_today: number;
  pnl_7d: number;
  open_positions: number;
  total_trades: number;
  wins: number;
  losses: number;
  auto_trade_on: boolean;
  kill_switch_active: boolean;
  trading_mode: string;
  active_preset: string | null;
  risk_profile: string;
  pnl_alltime: number;
  signals_today: number;
}

export interface PositionItem {
  id: string;
  market_id: string;
  market_question: string | null;
  side: string;
  size_usdc: number;
  entry_price: number;
  current_price: number | null;
  pnl_usdc: number | null;
  status: string;
  mode: string;
  opened_at: string;
  closed_at: string | null;
  exit_reason: string | null;
  tp_pct?: number | null;
  sl_pct?: number | null;
  tp_price?: number | null;
  sl_price?: number | null;
  awaiting_redeem?: boolean;
}

export interface MarketFeedItem {
  asset: string;
  label: string;
  up_prob: number;
  lean: "UP" | "DOWN" | "EVEN";
  seconds_to_close: number;
  liquidity_usdc: number;
}

export interface PortfolioSummary {
  available_usdc: number;
  realized_pnl: number;
  unrealized_pnl: number;
  equity_usdc: number;
  balance_usdc: number;
}

export interface ChartPoint {
  ts: string;
  equity: number;
}

export interface AutoTradeState {
  auto_trade_on: boolean;
  active_preset: string | null;
  risk_profile: string;
  capital_alloc_pct: number;
  tp_pct: number;
  sl_pct: number;
  market_categories: string[];
  min_liquidity: number;
  max_resolution_days: number | null;
  min_volume_24h: number;
  slippage_tolerance_pct: number | null;
  selected_timeframe: string | null;
  selected_assets: string[] | null;
  equity_usdc?: number | null;
  effective_max_per_trade_usdc?: number | null;
  max_per_trade_mode?: "auto" | "fixed" | "pct";
  max_per_trade_usdc?: number | null;
  max_per_trade_pct?: number | null;
  daily_loss_override?: number | null;   // negative $, e.g. -300
  max_drawdown_pct?: number | null;      // 0–0.08
}

export interface CustomizeParams {
  tp_pct?: number;
  sl_pct?: number;
  capital_alloc_pct?: number;
  max_position_pct?: number;
  auto_redeem_mode?: string;
  category_filters?: string[];
  max_per_trade_mode?: "auto" | "fixed" | "pct";
  max_per_trade_usdc?: number | null;
  max_per_trade_pct?: number | null;
  daily_loss_override?: number | null;   // negative $ value
  max_drawdown_pct?: number | null;      // 0 < x <= 0.08
}

export interface RiskProfileParams {
  profile: "conservative" | "balanced" | "aggressive" | "custom";
  capital_alloc_pct?: number;
  tp_pct?: number;
  sl_pct?: number;
}

export interface WalletInfo {
  deposit_address: string;
  balance_usdc: number;
  ledger_recent: LedgerEntry[];
  paper_mode?: boolean;
  trading_mode?: string;
}

export interface LedgerPage {
  entries: LedgerEntry[];
  has_more: boolean;
  total: number;
}

export interface LedgerEntry {
  id: string;
  type: string;
  amount_usdc: number;
  note: string | null;
  created_at: string;
}

export interface UserSettings {
  risk_profile: string;
  notifications_on: boolean;
  auto_redeem?: boolean;
  redeem_mode?: "instant" | "hourly";
}

export interface TradingSettings {
  auto_redeem?: boolean;
  redeem_mode?: "instant" | "hourly";
  min_liquidity_usd?: number;
  slippage_tolerance_pct?: number;
}

export interface OrderItem {
  id: string;
  market_id: string;
  market_question: string | null;
  side: string;
  size_usdc: number;
  price: number;
  status: string;
  mode: string;
  strategy_type: string | null;
  filled_amount: number;
  remaining_amount: number | null;
  created_at: string;
}

export interface ClosePositionResult {
  order_id: string | null;
  estimated_fill: number;
  status: string;
}

export interface MarketFilterSettings {
  market_categories: string[];
  min_liquidity: number;
  max_resolution_days: number | null;
  min_volume_24h: number;
}

export interface AlertItem {
  id: string;
  severity: string;
  title: string;
  body: string | null;
  created_at: string;
}

export interface CopyTask {
  id: string;
  wallet_address: string;
  nickname: string;
  status: "active" | "paused";
  copy_direction: string;
  copy_mode: string;
  copy_amount: number;
  execution_mode: string;
  allow_topups: boolean;
  created_at: string;
}

export interface CopyTaskCreate {
  wallet_address: string;
  nickname?: string;
  copy_direction?: string;
  copy_type?: string;
  amount?: number;
  execution_mode?: string;
  slippage_pct?: number;
  allow_topups?: boolean;
}

export interface CopyTaskPatch {
  nickname?: string;
  copy_direction?: string;
  execution_mode?: string;
  allow_topups?: boolean;
  status?: string;
}

export interface StrategyPnl {
  strategy: string;
  pnl_usdc: number;
}

export interface TradeHighlight {
  market_question: string | null;
  pnl_usdc: number;
}

export interface PortfolioAnalytics {
  has_data: boolean;
  max_drawdown_pct: number | null;
  profit_per_strategy: StrategyPnl[];
  best_trade: TradeHighlight | null;
  worst_trade: TradeHighlight | null;
  win_loss_ratio: number | null;
  wins: number;
  losses: number;
  avg_hold_hours: number | null;
}

export interface LeaderboardEntry {
  rank: number;
  wallet: string;
  alias: string | null;
  win_rate: number | null;
  total_pnl: number | null;
  volume_usdc: number | null;
  roi_pct: number | null;
  badge: string | null;
}

export interface RuntimeStatus {
  trading_mode: string;
  paper_mode: boolean;
  active_preset: string | null;
  risk_profile: string;
  kill_switch_active: boolean;
  open_positions: number;
  scanner_scanned: number;
  scanner_published: number;
  scanner_last_tick: number | null;
}

export interface FeedSignal {
  market_id: string;
  market_question: string;
  side: string;
  target_price: number | null;
  signal_type: string;
  published_at: string;
}

export interface Wallet360 {
  address: string;
  win_rate: number | null;
  roi: number | null;
  total_pnl: number | null;
  sharpe_ratio: number | null;
  max_drawdown: number | null;
  markets_traded: number | null;
  total_trades: number | null;
  performance_trend: string | null;
  risk_level: string | null;
  sybil_risk_flag: boolean;
  sybil_risk_score: number | null;
  combined_risk_score: number | null;
  flagged_metrics: string[] | null;
  last_active: string | null;
  available: boolean;
}
