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
    getMe: () => get<MeResponse>("/me"),
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
    requestWithdrawal: (amount_usdc: number, destination_address: string) =>
      post<WithdrawResponse>("/wallet/withdraw", { amount_usdc, destination_address }),
    getSettings: () => get<UserSettings>("/settings"),
    updateSettings: (data: Partial<UserSettings>) => patch<{ updated: boolean }>("/settings", data),
    getNotificationPrefs: () => get<{ prefs: NotificationPrefs }>("/settings/notification-prefs"),
    updateNotificationPrefs: (prefs: NotificationPrefs) =>
      patch<{ updated: boolean }>("/settings/notification-prefs", { prefs }),
    linkEmail: (email: string, password: string) =>
      post<{ ok: boolean }>("/auth/link-email", { email, password }),
    getAlerts: () => get<AlertItem[]>("/alerts"),
    /** Persist the "Mark all read" click server-side. Returns the new
     *  watermark (ISO-8601 with offset, or null on a never-acked account). */
    ackAllAlerts: () => post<{ alerts_ack_at: string | null }>("/alerts/ack-all", {}),
    getKillSwitch: () => get<{ active: boolean }>("/killswitch"),
    postKill: () => post<{ ok: boolean; user_paused: boolean }>("/kill"),
    postResume: () => post<{ ok: boolean; user_paused: boolean }>("/resume"),
    postEmergencyStop: () =>
      post<{ positions_marked: number; user_paused: boolean }>("/emergency-stop"),
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
    // ── Live-trading activation (per-user opt-in) ──────────────────────────
    getLiveStatus: () => get<LiveStatus>("/live/status"),
    enableLive: (live_capital_cap_usdc: number, confirm_phrase: string) =>
      post<LiveEnableResponse>("/live/enable", { live_capital_cap_usdc, confirm_phrase }),
    disableLive: () => post<{ trading_mode: string }>("/live/disable"),
    // ── Strategy picker availability (mirrors operator admin toggle) ───────
    getPresetAvailability: () =>
      get<{
        presets: { key: string; strategy: string; enabled: boolean }[];
        strategies: Record<string, boolean>;
      }>("/autotrade/preset-availability"),
    // ── Account unification — reverse Telegram-link ────────────────────────
    getLinkTelegramStatus: () => get<{ linked: boolean }>("/account/link-telegram/status"),
    startLinkTelegram: () => post<LinkTelegramStart>("/account/link-telegram/start"),
    // ── Admin console (role=admin only) ────────────────────────────────────
    getAdminOverview: () => get<AdminOverview>("/admin/overview"),
    getAdminUsers: (limit = 50, offset = 0) =>
      get<AdminUsersPage>(`/admin/users?limit=${limit}&offset=${offset}`),
    getAdminStrategies: () => get<{ strategies: AdminStrategy[] }>("/admin/strategies"),
    toggleStrategy: (name: string, enabled: boolean) =>
      post<{ name: string; enabled: boolean }>("/admin/strategies/toggle", { name, enabled }),
    getAdminUserDetail: (userId: string) =>
      get<AdminUserDetail>(`/admin/users/${encodeURIComponent(userId)}`),
    updateAdminUser: (userId: string, body: AdminUserPatch) =>
      patch<AdminUserDetail>(`/admin/users/${encodeURIComponent(userId)}`, body),
  };
}

// ── Admin console types ───────────────────────────────────────────────────
export interface AdminOverview {
  pool: { address: string | null; usdc: number | null; matic: number | null };
  polymarket: {
    funder_address: string | null;
    signature_type: number;
    use_real_clob: boolean;
    creds_source: string;   // "env" | "derived" | "none"
    creds_ready: boolean;
  };
  guards: Record<string, boolean>;
  kill_switch_active: boolean;
  counts: {
    users: number; admins: number; auto_trade_on: number; live_users: number;
    open_positions_paper: number; open_positions_live: number; total_wallet_usdc: number;
  };
  last_scan: Record<string, unknown> | null;
}

export interface AdminUser {
  user_id: string;
  username: string | null;
  email: string | null;
  role: string;
  trading_mode: string;
  active_preset: string | null;
  balance_usdc: number;
  auto_trade_on: boolean;
  paused: boolean;
  open_positions: number;
  created_at: string | null;
}

export interface AdminUsersPage {
  total: number;
  limit: number;
  offset: number;
  users: AdminUser[];
}

export interface AdminStrategy {
  name: string;
  enabled: boolean;
}

export interface AdminRecentTrade {
  id: string;
  status: string;
  side: string | null;
  size_usdc: number | null;
  entry_price: number | null;
  pnl_usdc: number | null;
  exit_reason: string | null;
  strategy_type: string | null;
  market_question: string;
  ts: string;
}

export interface AdminRecentAudit {
  ts: string;
  actor_role: string;
  action: string;
}

export interface AdminUserDetail {
  user_id: string;
  username: string | null;
  email: string | null;
  telegram_user_id: number | null;
  wallet_address: string | null;
  role: string;
  created_at: string | null;
  trading_mode: string;
  auto_trade_on: boolean;
  paused: boolean;
  open_positions: number;
  balance_usdc: number;
  active_preset: string | null;
  risk_profile: string;
  capital_alloc_pct: number;
  tp_pct: number | null;
  sl_pct: number | null;
  max_per_trade_mode: string;
  max_per_trade_usdc: number | null;
  max_per_trade_pct: number | null;
  selected_timeframe: string | null;
  selected_assets: string[] | null;
  recent_trades: AdminRecentTrade[];
  recent_audit: AdminRecentAudit[];
}

export interface AdminUserPatch {
  active_preset?: string;
  risk_profile?: string;
  capital_alloc_pct?: number;
  tp_pct?: number | null;
  sl_pct?: number | null;
  max_per_trade_mode?: string;
  max_per_trade_usdc?: number | null;
  max_per_trade_pct?: number | null;
  selected_timeframe?: string | null;
  selected_assets?: string[] | null;
  paused?: boolean;
}

export interface LinkTelegramStart {
  code: string;            // display form, e.g. "ABCD-EFGH"
  link_command: string;    // "/link ABCD-EFGH"
  expires_minutes: number;
  bot_username: string;    // "" when not configured
}

// Exact phrase the user must type to flip into live mode. MUST match the
// backend constant (domain/activation/live_opt_in_gate.LIVE_ENABLE_CONFIRM_PHRASE)
// and the Telegram flow — single source of truth across all three surfaces.
export const LIVE_ENABLE_CONFIRM_PHRASE = "ENABLE LIVE TRADING FOR MY ACCOUNT";
// Per-user live capital cap bounds (mirrors LIVE_CAP_MIN/MAX_USDC on the backend).
export const LIVE_CAP_MIN_USDC = 0;
export const LIVE_CAP_MAX_USDC = 10000;

// ── Types mirroring backend schemas ──────────────────────────────────────────

export interface MeResponse {
  user_id: string;
  first_name: string;
  username: string | null;
  email: string | null;        // null when no real email linked (tombstones excluded)
  telegram_linked: boolean;
  role: string;                // "user" | "admin"
  is_admin: boolean;
  trading_mode: string;        // "paper" | "live" — canonical per-user mode
}

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
  /** True when the strategy backing the active preset is globally enabled by
   *  the operator. False ≙ scanner emits no candidates regardless of the
   *  user's auto_trade_on flag. Optional for back-compat with older
   *  payloads — undefined is treated as enabled (FAIL-SAFE). */
  active_preset_globally_enabled?: boolean;
  /** Server-side "Mark all read" watermark — ISO-8601 with offset, or null
   *  on a never-acked account. Frontend folds it into markAllReadAt so the
   *  closed-position alert stream (fetched via /positions, not /alerts)
   *  honours the same cut-off as the server-filtered /alerts payload.
   *  Optional for back-compat with older payloads. */
  alerts_ack_at?: string | null;
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
  strategy_type?: string | null;
  active_preset?: string | null;
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
  total_closed: number;
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
  tp_pct: number | null;   // null when custom SL-only
  sl_pct: number | null;   // null when custom TP-only
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
  // False when the active preset's strategy is globally disabled by the operator.
  active_preset_globally_enabled?: boolean;
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

// Discriminator strings the backend writes into system_alerts.alert_kind.
// See monitoring/alerts.py + services/trade_notifications/notifier.py.
export type AlertKind =
  | "trade_opened"
  | "copy_trade_opened"
  | "tp_hit"
  | "sl_hit"
  | "resolution_win"
  | "resolution_loss"
  | "force_close"
  | "strategy_exit"
  | "manual_close"
  | "emergency_close"
  | "market_expired"
  | "close_failed"
  | "risk"
  | "system";

// Structured event metadata mirrored from notifier.notify_*. Every field is
// optional — legacy rows (pre-072 migration) have an empty {} so the typed
// card components fall back to the body text path.
export interface AlertMetadata {
  market_id?: string;
  market_label?: string;
  side?: string;
  size_usdc?: number;
  entry_price?: number;
  exit_price?: number;
  tp_pct?: number;
  sl_pct?: number;
  pnl_usdc?: number;
  strategy?: string;
  strategy_type?: string | null;
  mode?: string;
  position_id?: string | null;
  signal_reason?: string | null;
  copy_wallet?: string | null;
  copy_win_rate?: number | null;
  trade_id?: string | null;
  error?: string;
}

export interface AlertItem {
  id: string;
  severity: string;
  title: string;
  body: string | null;
  created_at: string;
  alert_kind?: AlertKind | string | null;
  metadata?: AlertMetadata;
}

// Per-alert × per-channel notification preferences. Missing keys / channels
// on the client default to true (fail-open) — matches the backend gate.
export type NotificationChannelPrefs = { web?: boolean; tg?: boolean };
export type NotificationPrefs = Record<string, NotificationChannelPrefs>;

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
  /** Global operator kill switch — informational only. Toggled by the
   * operator via /api/ops/kill or Telegram /kill, never by a normal
   * WebTrader user. */
  kill_switch_active: boolean;
  /** Per-user paused flag. Toggled by /api/web/kill, /api/web/resume,
   * and /api/web/emergency-stop. Independent of the global switch. */
  user_paused: boolean;
  open_positions: number;
  scanner_scanned: number;
  scanner_published: number;
  scanner_last_tick: number | null;
}

// ── Live-trading activation (mirrors backend schemas.LiveStatus/LiveEnable*) ──
export interface LiveStatus {
  trading_mode: string;            // "paper" | "live"
  live_capital_cap_usdc: number;   // 0 = not opted in
  open_live_exposure_usdc: number; // aggregate open live size
  operator_guards_open: boolean;   // system-level live unlock (all 5 env guards)
  checklist_passed: boolean;       // 8-gate per-user readiness
  failed_gates: string[];          // human-readable gate names that aren't passing
}

export interface LiveEnableResponse {
  trading_mode: string;
  live_capital_cap_usdc: number;
}

export interface FeedSignal {
  market_id: string;
  market_question: string;
  side: string;
  target_price: number | null;
  signal_type: string;
  published_at: string;
}

export interface WithdrawRequest {
  amount_usdc: number;
  destination_address: string;
}

export interface WithdrawResponse {
  id: string;
  status: string;
  approval_mode: string;
  amount_usdc: number;
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
