/**
 * WebSocket service for the PolyQuantBot dashboard.
 *
 * Features:
 *   - Auto-reconnect with exponential backoff (max 5 retries, capped at 30 s)
 *   - Heartbeat keepalive via aiohttp server-side heartbeat (15 s)
 *   - Message callback for incoming update payloads
 *   - Clean disconnect on unmount
 */

import type { PortfolioData, StatusData, Trade } from './api'

// ── Types ─────────────────────────────────────────────────────────────────────

export interface SignalEvent {
  ts: number
  [key: string]: unknown
}

export interface WsUpdatePayload {
  type: 'update'
  status: StatusData
  portfolio: PortfolioData
  trades: Trade[]
  signals: SignalEvent[]
}

export type WsMessageHandler = (payload: WsUpdatePayload) => void
export type WsStatusHandler = (connected: boolean) => void

// ── Constants ─────────────────────────────────────────────────────────────────

const WS_URL = `ws://${window.location.hostname}:8766/ws/dashboard`
const MAX_RETRIES = 5
const BASE_DELAY_MS = 1_000

// ── DashboardWebSocket ────────────────────────────────────────────────────────

export class DashboardWebSocket {
  private ws: WebSocket | null = null
  private retries = 0
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private closed = false

  constructor(
    private readonly onMessage: WsMessageHandler,
    private readonly onStatus: WsStatusHandler,
  ) {}

  /** Open the WebSocket connection. */
  connect(): void {
    if (this.closed) return
    try {
      this.ws = new WebSocket(WS_URL)
      this.ws.onopen = this._onOpen
      this.ws.onmessage = this._onMessage
      this.ws.onerror = this._onError
      this.ws.onclose = this._onClose
    } catch (err) {
      console.error('[DashboardWS] connect error', err)
      this._scheduleReconnect()
    }
  }

  /** Permanently close the connection (e.g. on component unmount). */
  disconnect(): void {
    this.closed = true
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    if (this.ws) {
      this.ws.onclose = null
      this.ws.close()
      this.ws = null
    }
    this.onStatus(false)
  }

  // ── Event handlers ──────────────────────────────────────────────────────────

  private readonly _onOpen = (): void => {
    this.retries = 0
    this.onStatus(true)
    console.info('[DashboardWS] connected')
  }

  private readonly _onMessage = (event: MessageEvent): void => {
    try {
      const payload = JSON.parse(event.data as string) as WsUpdatePayload
      if (payload.type === 'update') {
        this.onMessage(payload)
      }
    } catch (err) {
      console.warn('[DashboardWS] parse error', err)
    }
  }

  private readonly _onError = (event: Event): void => {
    console.warn('[DashboardWS] error', event)
  }

  private readonly _onClose = (): void => {
    this.onStatus(false)
    if (!this.closed) {
      this._scheduleReconnect()
    }
  }

  private _scheduleReconnect(): void {
    if (this.closed || this.retries >= MAX_RETRIES) {
      console.error('[DashboardWS] max retries reached — giving up')
      return
    }
    const delay = Math.min(BASE_DELAY_MS * 2 ** this.retries, 30_000)
    this.retries += 1
    console.info(`[DashboardWS] reconnecting in ${delay}ms (attempt ${this.retries}/${MAX_RETRIES})`)
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      this.connect()
    }, delay)
  }
}
