import { useState } from 'react'
import { postKill, postPause, postResume } from '../services/api'

interface Props {
  onBanner: (msg: string, error?: boolean) => void
}

export default function ControlPanel({ onBanner }: Props) {
  const [loading, setLoading] = useState<string | null>(null)

  async function dispatch(label: string, action: () => Promise<{ success: boolean; message: string }>) {
    setLoading(label)
    try {
      const result = await action()
      onBanner(result.message, !result.success)
    } catch (err) {
      onBanner(String(err), true)
    } finally {
      setLoading(null)
    }
  }

  return (
    <div style={styles.panel}>
      <h3 style={styles.title}>Controls</h3>
      <div style={styles.row}>
        <Button
          label="Pause"
          color="#f59e0b"
          disabled={loading !== null}
          loading={loading === 'pause'}
          onClick={() => dispatch('pause', postPause)}
        />
        <Button
          label="Resume"
          color="#22c55e"
          disabled={loading !== null}
          loading={loading === 'resume'}
          onClick={() => dispatch('resume', postResume)}
        />
        <Button
          label="Kill"
          color="#ef4444"
          disabled={loading !== null}
          loading={loading === 'kill'}
          onClick={() => dispatch('kill', postKill)}
        />
      </div>
    </div>
  )
}

interface BtnProps {
  label: string
  color: string
  disabled: boolean
  loading: boolean
  onClick: () => void
}

function Button({ label, color, disabled, loading, onClick }: BtnProps) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        background: disabled ? '#334155' : color,
        color: '#fff',
        border: 'none',
        borderRadius: '0.375rem',
        padding: '0.5rem 1.25rem',
        fontWeight: 700,
        fontSize: '0.875rem',
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.6 : 1,
        transition: 'opacity 0.15s',
      }}
    >
      {loading ? '…' : label}
    </button>
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
  row: {
    display: 'flex',
    gap: '0.75rem',
    flexWrap: 'wrap',
  },
}
