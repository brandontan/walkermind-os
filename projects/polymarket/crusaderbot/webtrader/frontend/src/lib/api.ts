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
    getDashboard: () => get<DashboardSummary>("/dashboard"),
    getPositions: (status?: string) =>
      get<PositionItem[]>(`/positions${status ? `?status=${status}` : ""}`),
    getAutotrade: () => get<AutoTradeState>("/autotrade"),
    toggleAutotrade: (enabled: boolean) => post<{ auto_trade_on: boolean }>("/autotrade/toggle", { enabled }),
    activatePreset: (preset_key: string) => post<{ active_preset: string }>("/autotrade/preset", { preset_key }),
    customizeStrategy: (params: CustomizeParams) => post<{ updated: boolean }>("/autotrade/customize", params),
    getWallet: () => get<WalletInfo>("/wallet"),
    getSettings: () => get<UserSettings>("/settings"),
    updateSettings: (data: Partial<UserSettings>) => patch<{ updated: boolean }>("/settings", data),
    getAlerts: () => get<AlertItem[]>("/alerts"),
    getKillSwitch: () => get<{ active: boolean }>("/killswitch"),
    postKill: () => post<{ ok: boolean }>("/kill"),
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
}

export interface AutoTradeState {
  auto_trade_on: boolean;
  active_preset: string | null;
  risk_profile: string;
  capital_alloc_pct: number;
  tp_pct: number;
  sl_pct: number;
}

export interface CustomizeParams {
  tp_pct?: number;
  sl_pct?: number;
  capital_alloc_pct?: number;
  max_position_pct?: number;
  auto_redeem_mode?: string;
  category_filters?: string[];
}

export interface WalletInfo {
  deposit_address: string;
  balance_usdc: number;
  ledger_recent: LedgerEntry[];
}

export interface LedgerEntry {
  type: string;
  amount_usdc: number;
  note: string | null;
  created_at: string;
}

export interface UserSettings {
  risk_profile: string;
  notifications_on: boolean;
}

export interface AlertItem {
  id: string;
  severity: string;
  title: string;
  body: string | null;
  created_at: string;
}
