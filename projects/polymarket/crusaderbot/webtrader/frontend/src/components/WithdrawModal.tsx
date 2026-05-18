interface Props {
  paperMode: boolean;
  balance: number;
  onClose: () => void;
}

export function WithdrawModal({ paperMode, balance, onClose }: Props) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-end md:items-center justify-center"
      style={{ background: "rgba(0,0,0,0.78)" }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
      role="dialog"
      aria-modal="true"
      aria-label="Withdraw USDC"
    >
      <div
        className="w-full max-w-sm bg-surface border border-border-1 clip-card p-5 pb-8 md:pb-5"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <p className="font-hud text-[11px] font-bold tracking-[2px] uppercase text-gold">
            Withdraw USDC
          </p>
          <button
            type="button"
            onClick={onClose}
            className="text-ink-3 hover:text-ink-1 text-[20px] leading-none p-1 ml-2 flex-shrink-0"
            aria-label="Close"
          >
            ×
          </button>
        </div>

        {paperMode ? (
          <div className="space-y-3">
            <div
              className="p-3.5 rounded-sm text-center"
              style={{
                background: "rgba(255,45,85,0.06)",
                border: "1px solid rgba(255,45,85,0.22)",
              }}
            >
              <p
                className="font-hud text-[10px] font-bold tracking-[1.5px] uppercase mb-1"
                style={{ color: "#FF6B6B" }}
              >
                Withdraw unavailable in Paper Mode
              </p>
              <p className="text-[9px] font-mono text-ink-3">
                No real funds at risk — Paper Mode is active.
              </p>
            </div>
            <p className="text-[9px] font-mono text-ink-4 text-center">
              Balance: ${balance.toFixed(2)} USDC (paper)
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            <div
              className="p-3.5 rounded-sm text-center"
              style={{
                background: "rgba(245,200,66,0.06)",
                border: "1px solid rgba(245,200,66,0.22)",
              }}
            >
              <p className="font-hud text-[10px] font-bold tracking-[1.5px] uppercase text-gold mb-1">
                Use Telegram Bot to Withdraw
              </p>
              <p className="text-[9px] font-mono text-ink-3">
                Web withdrawal is not available in this version.
                Open the Telegram bot and use the Withdraw command.
              </p>
            </div>
            <p className="text-[9px] font-mono text-ink-4 text-center">
              Available: ${balance.toFixed(2)} USDC
            </p>
          </div>
        )}

        <button
          type="button"
          onClick={onClose}
          className="w-full mt-4 clip-btn font-hud text-[10px] font-bold tracking-[1.5px] uppercase py-2.5 text-ink-3 transition-colors"
          style={{
            background: "rgba(255,255,255,0.04)",
            border: "1px solid rgba(255,255,255,0.08)",
          }}
        >
          Close
        </button>
      </div>
    </div>
  );
}
