import type { PortfolioData } from '../services/api'

interface Props {
  portfolio: PortfolioData | null
}

function fmt(v: number | null, decimals = 2): string {
  if (v === null || v === undefined) return '—'
  return v.toFixed(decimals)
}

export default function PortfolioPanel({ portfolio }: Props) {
  return (
    <div style={styles.panel}>
      <h3 style={styles.title}>Portfolio</h3>
      <div style={styles.grid}>
        <Stat label="Balance" value={fmt(portfolio?.balance ?? null)} />
        <Stat label="PnL Today" value={fmt(portfolio?.pnl_today ?? null)} />
        <Stat label="PnL All-Time" value={fmt(portfolio?.pnl_all_time ?? null)} />
        <Stat
          label="Drawdown"
          value={portfolio?.drawdown_pct !== null && portfolio?.drawdown_pct !== undefined
            ? `${fmt(portfolio.drawdown_pct)}%`
            : '—'}
        />
        <Stat
          label="Fill Rate"
          value={portfolio?.fill_rate !== null && portfolio?.fill_rate !== undefined
            ? `${(portfolio.fill_rate * 100).toFixed(1)}%`
            : '—'}
        />
        <Stat
          label="Active Trades"
          value={portfolio?.active_trades !== null && portfolio?.active_trades !== undefined
            ? String(portfolio.active_trades)
            : '—'}
        />
      </div>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div style={styles.stat}>
      <div style={styles.label}>{label}</div>
      <div style={styles.value}>{value}</div>
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
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))',
    gap: '0.75rem',
  },
  stat: {
    background: '#0f172a',
    borderRadius: '0.375rem',
    padding: '0.5rem 0.75rem',
  },
  label: {
    fontSize: '0.7rem',
    color: '#64748b',
    marginBottom: '0.25rem',
  },
  value: {
    fontSize: '1rem',
    fontWeight: 600,
    color: '#e2e8f0',
  },
}
