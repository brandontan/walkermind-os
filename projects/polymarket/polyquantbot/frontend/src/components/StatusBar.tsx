import type { StatusData } from '../services/api'

interface Props {
  status: StatusData | null
  wsConnected: boolean
}

const STATE_COLOR: Record<string, string> = {
  RUNNING: '#22c55e',
  PAUSED: '#f59e0b',
  HALTED: '#ef4444',
}

export default function StatusBar({ status, wsConnected }: Props) {
  const state = status?.system_state ?? '—'
  const mode = status?.mode ?? '—'
  const color = STATE_COLOR[state] ?? '#6b7280'

  return (
    <div style={styles.bar}>
      <span style={{ ...styles.badge, background: color }}>{state}</span>
      <span style={styles.item}>Mode: <strong>{mode}</strong></span>
      <span style={{ ...styles.badge, background: wsConnected ? '#22c55e' : '#ef4444', marginLeft: 'auto' }}>
        {wsConnected ? '● Live' : '○ Disconnected'}
      </span>
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  bar: {
    display: 'flex',
    alignItems: 'center',
    gap: '1rem',
    padding: '0.5rem 1rem',
    background: '#1e293b',
    borderBottom: '1px solid #334155',
    fontSize: '0.875rem',
    color: '#e2e8f0',
  },
  badge: {
    padding: '0.2rem 0.6rem',
    borderRadius: '0.25rem',
    color: '#fff',
    fontWeight: 700,
    fontSize: '0.75rem',
  },
  item: {
    color: '#94a3b8',
  },
}
