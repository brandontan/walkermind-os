const BASE = "/api/web";

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
    const text = await res.text().catch(() => "unknown error");
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
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
    getPositions: (status?: string, limit?: number) => {
      const params = new URLSearchParams();
      if (status) params.set("status", status);
      if (limit) params.set("limit", String(limit));
      const qs = params.toString();
      return get<PositionItem[]>(`/positions${qs ? `?${qs}` : ""}`);
    },
    getPortfolioSummary: () => get<PortfolioSummary>("/portfolio/summary"),
    getPortfolioChart: (period: string) =>
      get<ChartPoint[]>(`/portfolio/chart?period=${encodeURIComponent(period)}`),
    getAutotrade: () => get<AutoTradeState>("/autotrade"),
    toggleAutotrade: (enabled: boolean) => post<{ auto_trade_on: boolean }>("/autotrade/toggle", { enabled }),
    activatePreset: (preset_key: string) => post<{ active_preset: string }>("/autotrade/preset", { preset_key }),
    setRiskProfile: (params: RiskProfileParams) => patch<{ risk_profile: string }>("/autotrade/risk-profile", params),
    customizeStrategy: (params: CustomizeParams) => post<{ updated: boolean }>("/autotrade/customize", params),
    getWallet: () => get<WalletInfo>("/wallet"),
    getLedger: (offset: number, limit = 20) =>
      get<LedgerPage>(`/wallet/ledger?offset=${offset}&limit=${limit}`),
    getSettings: () => get<UserSettings>("/settings"),
    updateSettings: (data: Partial<UserSettings>) => patch<{ updated: boolean }>("/settings", data),
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
    getOrders: (limit?: number) => {
      const params = new URLSearchParams();
      if (limit) params.set("limit", String(limit));
      const qs = params.toString();
      return get<OrderItem[]>(`/orders${qs ? `?${qs}` : ""}`);
    },
    closePosition: (positionId: string) =>
      post<ClosePositionResult>(`/positions/${positionId}/close`),
    getPortfolioAnalytics: () => get<PortfolioAnalytics>("/portfolio/analytics"),
    getLeaderboard: () => get<LeaderboardEntry[]>("/leaderboard"),
    getWallet360: (address: string) =>
      get<Wallet360>(`/copy-trade/wallet-360/${address}`),
    getRecentSignals: (limit = 10) =>
      get<FeedSignal[]>(`/signals/recent?limit=${limit}`),
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
}

export interface CustomizeParams {
  tp_pct?: number;
  sl_pct?: number;
  capital_alloc_pct?: number;
  max_position_pct?: number;
  auto_redeem_mode?: string;
  category_filters?: string[];
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
