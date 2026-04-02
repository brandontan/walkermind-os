import type { Trade } from '../services/api'

interface Props {
  trades: Trade[]
}

function fmt(v: number | null, d = 4): string {
  return v !== null && v !== undefined ? v.toFixed(d) : '—'
}

export default function TradeTable({ trades }: Props) {
  return (
    <div style={styles.panel}>
      <h3 style={styles.title}>Open Trades ({trades.length})</h3>
      {trades.length === 0 ? (
        <p style={styles.empty}>No open trades.</p>
      ) : (
        <div style={styles.tableWrap}>
          <table style={styles.table}>
            <thead>
              <tr>
                {['Market', 'Side', 'Price', 'Size', 'PnL'].map(h => (
                  <th key={h} style={styles.th}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {trades.map(t => (
                <tr key={t.order_id} style={styles.tr}>
                  <td style={styles.td}>{t.market ?? '—'}</td>
                  <td style={{ ...styles.td, color: t.side === 'BUY' ? '#22c55e' : '#f87171' }}>
                    {t.side ?? '—'}
                  </td>
                  <td style={styles.td}>{fmt(t.price)}</td>
                  <td style={styles.td}>{fmt(t.size)}</td>
                  <td style={{ ...styles.td, color: (t.pnl ?? 0) >= 0 ? '#22c55e' : '#f87171' }}>
                    {fmt(t.pnl, 2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
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
  tableWrap: {
    overflowX: 'auto',
  },
  table: {
    width: '100%',
    borderCollapse: 'collapse',
    fontSize: '0.8rem',
  },
  th: {
    textAlign: 'left',
    padding: '0.4rem 0.5rem',
    color: '#64748b',
    fontWeight: 600,
    borderBottom: '1px solid #334155',
  },
  tr: {},
  td: {
    padding: '0.35rem 0.5rem',
    color: '#e2e8f0',
    borderBottom: '1px solid #1e293b',
  },
}
