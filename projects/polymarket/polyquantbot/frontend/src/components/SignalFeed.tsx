import type { SignalEvent } from '../services/websocket'

interface Props {
  signals: SignalEvent[]
}

function formatTs(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString()
}

export default function SignalFeed({ signals }: Props) {
  const recent = [...signals].reverse().slice(0, 20)

  return (
    <div style={styles.panel}>
      <h3 style={styles.title}>Signal Feed (last 20)</h3>
      {recent.length === 0 ? (
        <p style={styles.empty}>Waiting for signals…</p>
      ) : (
        <ul style={styles.list}>
          {recent.map((s, i) => (
            <li key={i} style={styles.item}>
              <span style={styles.time}>{formatTs(s.ts)}</span>
              <span style={styles.text}>{JSON.stringify(s, (k, v) => k === 'ts' ? undefined : v)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  panel: {
    background: '#1e293b',
    border: '1px solid #334155',
    borderRadius: '0.5rem',
    padding: '1rem',
  },
  title: {
    margin: '0 0 0.75rem',
    fontSize: '0.875rem',
    fontWeight: 700,
    color: '#94a3b8',
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
  },
  empty: {
    color: '#64748b',
    fontSize: '0.85rem',
    margin: 0,
  },
  list: {
    listStyle: 'none',
    margin: 0,
    padding: 0,
    maxHeight: '240px',
    overflowY: 'auto',
  },
  item: {
    display: 'flex',
    gap: '0.5rem',
    padding: '0.25rem 0',
    borderBottom: '1px solid #0f172a',
    fontSize: '0.75rem',
  },
  time: {
    color: '#64748b',
    whiteSpace: 'nowrap',
    flexShrink: 0,
  },
  text: {
    color: '#94a3b8',
    wordBreak: 'break-all',
  },
}
