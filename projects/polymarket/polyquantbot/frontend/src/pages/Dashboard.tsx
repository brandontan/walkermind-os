import { useCallback, useEffect, useRef, useState } from 'react'
import ControlPanel from '../components/ControlPanel'
import PortfolioPanel from '../components/PortfolioPanel'
import SignalFeed from '../components/SignalFeed'
import StatusBar from '../components/StatusBar'
import TradeTable from '../components/TradeTable'
import type { PortfolioData, StatusData, Trade } from '../services/api'
import { type SignalEvent, type WsUpdatePayload, DashboardWebSocket } from '../services/websocket'

interface Banner {
  message: string
  error: boolean
}

export default function Dashboard() {
  const [status, setStatus] = useState<StatusData | null>(null)
  const [portfolio, setPortfolio] = useState<PortfolioData | null>(null)
  const [trades, setTrades] = useState<Trade[]>([])
  const [signals, setSignals] = useState<SignalEvent[]>([])
  const [wsConnected, setWsConnected] = useState(false)
  const [banner, setBanner] = useState<Banner | null>(null)

  const wsRef = useRef<DashboardWebSocket | null>(null)

  const handleMessage = useCallback((payload: WsUpdatePayload) => {
    setStatus(payload.status)
    setPortfolio(payload.portfolio)
    setTrades(payload.trades)
    setSignals(payload.signals)
  }, [])

  const handleWsStatus = useCallback((connected: boolean) => {
    setWsConnected(connected)
    if (!connected) {
      setBanner({ message: 'WebSocket disconnected — reconnecting…', error: true })
    } else {
      setBanner(prev => (prev?.error ? null : prev))
    }
  }, [])

  useEffect(() => {
    const ws = new DashboardWebSocket(handleMessage, handleWsStatus)
    wsRef.current = ws
    ws.connect()
    return () => {
      ws.disconnect()
      wsRef.current = null
    }
  }, [handleMessage, handleWsStatus])

  // Auto-dismiss info banners after 4 s
  useEffect(() => {
    if (!banner) return
    const t = setTimeout(() => setBanner(null), 4_000)
    return () => clearTimeout(t)
  }, [banner])

  const showBanner = useCallback((message: string, error = false) => {
    setBanner({ message, error })
  }, [])

  return (
    <div style={styles.root}>
      <StatusBar status={status} wsConnected={wsConnected} />

      {banner && (
        <div style={{ ...styles.banner, background: banner.error ? '#7f1d1d' : '#14532d' }}>
          {banner.message}
          <button style={styles.dismiss} onClick={() => setBanner(null)}>✕</button>
        </div>
      )}

      <div style={styles.body}>
        <div style={styles.grid}>
          <div style={styles.span2}>
            <PortfolioPanel portfolio={portfolio} />
          </div>
          <ControlPanel onBanner={showBanner} />
          <div style={styles.span2}>
            <TradeTable trades={trades} />
          </div>
          <SignalFeed signals={signals} />
        </div>
      </div>
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  root: {
    minHeight: '100vh',
    background: '#0f172a',
    color: '#e2e8f0',
    fontFamily: 'system-ui, sans-serif',
    display: 'flex',
    flexDirection: 'column',
  },
  banner: {
    padding: '0.5rem 1rem',
    fontSize: '0.85rem',
    color: '#fff',
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  dismiss: {
    background: 'transparent',
    border: 'none',
    color: '#fff',
    cursor: 'pointer',
    fontSize: '0.85rem',
  },
  body: {
    flex: 1,
    padding: '1rem',
    overflowY: 'auto',
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(3, 1fr)',
    gap: '1rem',
  },
  span2: {
    gridColumn: 'span 2',
  },
}
