import { useCallback, useEffect, useMemo, useState } from "react";
import { TopBar } from "../components/TopBar";
import { makeApi } from "../lib/api";
import { useAuth } from "../lib/auth";

interface CopyTask {
  id: string;
  wallet_address: string;
  nickname: string;
  status: "active" | "paused";
  copy_direction: string;
  copy_mode: string;
  copy_amount: number;
  execution_mode: string;
  allow_topups: boolean;
  created_at: string;
}

function truncateWallet(addr: string): string {
  if (addr.length < 12) return addr;
  return `${addr.slice(0, 8)}…${addr.slice(-4)}`;
}

export function CopyTradePage() {
  const { user } = useAuth();
  const api = useMemo(() => makeApi(user?.token ?? null), [user?.token]);
  const [tasks, setTasks] = useState<CopyTask[]>([]);
  const [loading, setLoading] = useState(false);

  // Add form state
  const [wallet, setWallet] = useState("");
  const [nickname, setNickname] = useState("");
  const [direction, setDirection] = useState<"buys_only" | "buys_and_sells">("buys_only");
  const [copyType, setCopyType] = useState<"fixed" | "percentage" | "rm">("fixed");
  const [amount, setAmount] = useState("10");
  const [execMode, setExecMode] = useState<"auto" | "manual">("auto");
  const [slippage, setSlippage] = useState<"5" | "10">("5");
  const [allowTopups, setAllowTopups] = useState(true);
  const [formErr, setFormErr] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [showForm, setShowForm] = useState(false);

  const load = useCallback(async () => {
    const data = await api.listCopyTasks();
    setTasks(data);
  }, [api]);

  useEffect(() => { void load(); }, [load]);

  async function handleToggle(id: string, current: string) {
    setLoading(true);
    try {
      await api.updateCopyTask(id, { status: current === "active" ? "paused" : "active" });
      await load();
    } finally {
      setLoading(false);
    }
  }

  async function handleDelete(id: string) {
    setLoading(true);
    try {
      await api.deleteCopyTask(id);
      await load();
    } finally {
      setLoading(false);
    }
  }

  async function handleAdd() {
    setFormErr(null);
    if (!wallet.trim().match(/^0x[0-9a-fA-F]{40}$/)) {
      setFormErr("Enter a valid 0x wallet address.");
      return;
    }
    const amt = parseFloat(amount);
    if (isNaN(amt) || amt <= 0) {
      setFormErr("Amount must be a positive number.");
      return;
    }
    setSaving(true);
    try {
      await api.createCopyTask({
        wallet_address: wallet.trim().toLowerCase(),
        nickname: nickname.trim() || undefined,
        copy_direction: direction,
        copy_type: copyType,
        amount: amt,
        execution_mode: execMode,
        slippage_pct: parseFloat(slippage) / 100,
        allow_topups: allowTopups,
      });
      setWallet(""); setNickname(""); setAmount("10");
      setShowForm(false);
      await load();
    } catch (e: unknown) {
      setFormErr(e instanceof Error ? e.message : "Failed to add target.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <TopBar />
      <div className="px-3.5 pt-3.5 pb-6 animate-page-in">

        {/* Header */}
        <div className="flex items-center justify-between mt-1 mb-3 mx-0.5">
          <div className="font-hud text-[10px] font-bold tracking-[3px] text-ink-2 uppercase flex items-center gap-2">
            <span className="w-3 h-px bg-gold" aria-hidden />
            Copy Trade
          </div>
          <button
            onClick={() => setShowForm(v => !v)}
            className="font-hud text-[9px] font-bold tracking-widest text-gold uppercase px-2 py-1 rounded border border-gold/40 bg-gold/10 hover:bg-gold/20"
          >
            {showForm ? "← Cancel" : "+ Add Target"}
          </button>
        </div>

        {/* Active Targets */}
        {tasks.length === 0 && !showForm && (
          <p className="text-ink-3 text-xs font-mono text-center py-8">
            No copy targets yet. Add a wallet to start mirroring trades.
          </p>
        )}

        <div className="space-y-2">
          {tasks.map((t) => (
            <div
              key={t.id}
              className="p-3 rounded-lg border border-surface-3 bg-surface-1"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="font-hud text-sm font-bold text-ink-1 flex items-center gap-2">
                    🐋 {t.nickname}
                    <span className={`text-[9px] font-bold tracking-widest uppercase px-1.5 py-0.5 rounded border ${
                      t.status === "active"
                        ? "text-grn border-grn/40 bg-grn/10"
                        : "text-ink-3 border-ink-4/40 bg-surface-2"
                    }`}>
                      {t.status.toUpperCase()}
                    </span>
                  </div>
                  <div className="text-[10px] text-ink-4 font-mono mt-0.5">
                    {truncateWallet(t.wallet_address)}
                  </div>
                  <div className="text-[10px] text-ink-3 mt-1 flex gap-2 flex-wrap">
                    <span>{t.copy_direction === "buys_only" ? "📈 Buys only" : "🔄 Buys & Sells"}</span>
                    <span className="text-ink-4">·</span>
                    <span>{t.execution_mode === "auto" ? "⚡ Auto" : "✋ Manual"}</span>
                    <span className="text-ink-4">·</span>
                    <span>{t.allow_topups ? "➕ Top-ups" : "🚫 No top-ups"}</span>
                  </div>
                </div>
                <div className="shrink-0 flex flex-col gap-1">
                  <button
                    disabled={loading}
                    onClick={() => void handleToggle(t.id, t.status)}
                    className="text-[9px] font-bold text-ink-2 px-2 py-0.5 rounded border border-surface-3 hover:border-ink-3 disabled:opacity-40"
                  >
                    {t.status === "active" ? "⏸ Pause" : "▶ Resume"}
                  </button>
                  <button
                    disabled={loading}
                    onClick={() => void handleDelete(t.id)}
                    className="text-[9px] font-bold text-red-400 px-2 py-0.5 rounded border border-red-900/40 hover:border-red-400/60 disabled:opacity-40"
                  >
                    🗑 Delete
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Add Form */}
        {showForm && (
          <div className="mt-4 p-3 rounded-lg border border-surface-3 bg-surface-1 space-y-3">
            <div className="font-hud text-[10px] font-bold tracking-[3px] text-ink-2 uppercase flex items-center gap-2">
              <span className="w-3 h-px bg-gold" aria-hidden />
              Add Copy Target
            </div>

            <div className="space-y-2">
              <div>
                <label className="text-[9px] text-ink-4 uppercase block mb-0.5">Wallet Address *</label>
                <input
                  type="text"
                  placeholder="0x..."
                  value={wallet}
                  onChange={e => setWallet(e.target.value)}
                  className="w-full bg-surface-3 border border-ink-4 rounded px-2 py-1.5 text-xs font-mono text-ink-1 focus:border-gold focus:outline-none"
                />
              </div>

              <div>
                <label className="text-[9px] text-ink-4 uppercase block mb-0.5">Nickname</label>
                <input
                  type="text"
                  placeholder="Bull Whale"
                  value={nickname}
                  onChange={e => setNickname(e.target.value)}
                  className="w-full bg-surface-3 border border-ink-4 rounded px-2 py-1.5 text-xs font-mono text-ink-1 focus:border-gold focus:outline-none"
                />
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-[9px] text-ink-4 uppercase block mb-0.5">Copy Direction</label>
                  <select
                    value={direction}
                    onChange={e => setDirection(e.target.value as typeof direction)}
                    className="w-full bg-surface-3 border border-ink-4 rounded px-2 py-1.5 text-xs font-mono text-ink-1 focus:border-gold focus:outline-none"
                  >
                    <option value="buys_only">Buys Only</option>
                    <option value="buys_and_sells">Buys & Sells</option>
                  </select>
                </div>
                <div>
                  <label className="text-[9px] text-ink-4 uppercase block mb-0.5">Copy Type</label>
                  <select
                    value={copyType}
                    onChange={e => setCopyType(e.target.value as typeof copyType)}
                    className="w-full bg-surface-3 border border-ink-4 rounded px-2 py-1.5 text-xs font-mono text-ink-1 focus:border-gold focus:outline-none"
                  >
                    <option value="fixed">Fixed $</option>
                    <option value="percentage">Percentage %</option>
                    <option value="rm">RM Mirror</option>
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-[9px] text-ink-4 uppercase block mb-0.5">
                    {copyType === "fixed" ? "Amount ($)" : "Amount (%)"}
                  </label>
                  <input
                    type="number"
                    min={0.01}
                    step={0.01}
                    value={amount}
                    onChange={e => setAmount(e.target.value)}
                    className="w-full bg-surface-3 border border-ink-4 rounded px-2 py-1.5 text-xs font-mono text-ink-1 focus:border-gold focus:outline-none"
                  />
                </div>
                <div>
                  <label className="text-[9px] text-ink-4 uppercase block mb-0.5">Slippage</label>
                  <select
                    value={slippage}
                    onChange={e => setSlippage(e.target.value as typeof slippage)}
                    className="w-full bg-surface-3 border border-ink-4 rounded px-2 py-1.5 text-xs font-mono text-ink-1 focus:border-gold focus:outline-none"
                  >
                    <option value="5">5%</option>
                    <option value="10">10%</option>
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-[9px] text-ink-4 uppercase block mb-0.5">Execution</label>
                  <select
                    value={execMode}
                    onChange={e => setExecMode(e.target.value as typeof execMode)}
                    className="w-full bg-surface-3 border border-ink-4 rounded px-2 py-1.5 text-xs font-mono text-ink-1 focus:border-gold focus:outline-none"
                  >
                    <option value="auto">Auto (Instant)</option>
                    <option value="manual">Manual (Confirm)</option>
                  </select>
                </div>
                <div>
                  <label className="text-[9px] text-ink-4 uppercase block mb-0.5">Allow Top-ups</label>
                  <select
                    value={allowTopups ? "yes" : "no"}
                    onChange={e => setAllowTopups(e.target.value === "yes")}
                    className="w-full bg-surface-3 border border-ink-4 rounded px-2 py-1.5 text-xs font-mono text-ink-1 focus:border-gold focus:outline-none"
                  >
                    <option value="yes">Yes</option>
                    <option value="no">No</option>
                  </select>
                </div>
              </div>
            </div>

            {formErr && <p className="text-xs text-red-400">{formErr}</p>}

            <button
              onClick={() => void handleAdd()}
              disabled={saving}
              className="w-full py-2 rounded bg-gold/20 border border-gold/40 text-gold text-xs font-bold hover:bg-gold/30 disabled:opacity-50"
            >
              {saving ? "Adding…" : "🐋 Start Copying"}
            </button>
          </div>
        )}
      </div>
    </>
  );
}
