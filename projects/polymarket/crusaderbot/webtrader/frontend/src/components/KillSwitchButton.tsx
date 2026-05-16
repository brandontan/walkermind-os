import { useState } from "react";

interface KillSwitchButtonProps {
  onKill: () => Promise<void>;
  active: boolean;
}

export function KillSwitchButton({ onKill, active }: KillSwitchButtonProps) {
  const [confirming, setConfirming] = useState(false);
  const [loading, setLoading] = useState(false);

  async function handleConfirm() {
    setLoading(true);
    try {
      await onKill();
    } finally {
      setLoading(false);
      setConfirming(false);
    }
  }

  if (active) {
    return (
      <div className="bg-red/10 border border-red/30 rounded-xl p-4 text-center">
        <p className="text-red font-semibold text-sm">⛔ Kill Switch Active</p>
        <p className="text-muted text-xs mt-1">All new trades are blocked</p>
      </div>
    );
  }

  if (confirming) {
    return (
      <div className="bg-red/10 border border-red/30 rounded-xl p-4">
        <p className="text-red font-semibold text-sm mb-1">⚠ Confirm Kill Switch</p>
        <p className="text-muted text-xs mb-4">This will halt all trades immediately.</p>
        <div className="flex gap-3">
          <button
            onClick={() => setConfirming(false)}
            className="flex-1 py-2 rounded-lg border border-border text-muted text-sm"
          >
            Cancel
          </button>
          <button
            onClick={handleConfirm}
            disabled={loading}
            className="flex-1 py-2 rounded-lg bg-red text-white text-sm font-semibold disabled:opacity-60"
          >
            {loading ? "Stopping…" : "STOP ALL"}
          </button>
        </div>
      </div>
    );
  }

  return (
    <button
      onClick={() => setConfirming(true)}
      className="w-full py-3 rounded-xl bg-red/10 border border-red/30 text-red font-semibold text-sm hover:bg-red/20 transition-colors"
    >
      ⛔ Emergency Stop
    </button>
  );
}
