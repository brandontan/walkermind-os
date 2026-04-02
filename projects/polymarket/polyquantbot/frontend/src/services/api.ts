/**
 * REST API service for the PolyQuantBot dashboard.
 *
 * All fetch calls are lightweight (no heavy queries) and return typed
 * responses.  On error, the function throws so the caller can display a
 * banner without crashing the component tree.
 */

const BASE = '/api'

// ── Types ─────────────────────────────────────────────────────────────────────

export interface StatusData {
  system_state: 'RUNNING' | 'PAUSED' | 'HALTED'
  mode: 'PAPER' | 'LIVE'
  reason: string
  state_changed_at: number | null
  ts: number
}

export interface PortfolioData {
  balance: number | null
  pnl_today: number | null
  pnl_all_time: number | null
  exposure: number | null
  active_trades: number | null
  drawdown_pct?: number | null
  fill_rate?: number | null
}

export interface Trade {
  order_id: string
  market: string | null
  side: string | null
  price: number | null
  size: number | null
  pnl: number | null
  ts: number | null
}

export interface ControlResult {
  success: boolean
  message: string
  payload?: Record<string, unknown>
}

// ── Helpers ───────────────────────────────────────────────────────────────────

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(`API ${path} → ${res.status}: ${text}`)
  }
  return res.json() as Promise<T>
}

// ── Public API ────────────────────────────────────────────────────────────────

export const fetchStatus = (): Promise<StatusData> =>
  apiFetch<StatusData>('/status')

export const fetchPortfolio = (): Promise<PortfolioData> =>
  apiFetch<PortfolioData>('/portfolio')

export const fetchTrades = (): Promise<{ trades: Trade[] }> =>
  apiFetch<{ trades: Trade[] }>('/trades')

export const postPause = (): Promise<ControlResult> =>
  apiFetch<ControlResult>('/pause', { method: 'POST' })

export const postResume = (): Promise<ControlResult> =>
  apiFetch<ControlResult>('/resume', { method: 'POST' })

export const postKill = (): Promise<ControlResult> =>
  apiFetch<ControlResult>('/kill', { method: 'POST' })
