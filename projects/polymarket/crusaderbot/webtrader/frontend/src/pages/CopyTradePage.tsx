import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { CollapsibleSection } from "../components/CollapsibleSection";
import { FilterTabs, type FilterTab } from "../components/FilterTabs";
import { TopBar } from "../components/TopBar";
import { TxHash } from "../components/TxHash";
import { makeApi, type LeaderboardEntry, type Wallet360 } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useSSE } from "../lib/sse";

type CopyTab = "manual" | "leaderboard";

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

export function PageTabs({ active, onSwitch }: { active: "auto" | "copy"; onSwitch: (tab: "auto" | "copy") => void }) {
  return (
    <div
      className="flex border-b border-border-1 px-3.5"
      style={{ background: "rgba(2,5,11,0.6)" }}
    >
      {(["auto", "copy"] as const).map((t) => {
        const isActive = active === t;
        return (
          <button
            key={t}
            onClick={() => onSwitch(t)}
            className={[
              "py-2.5 px-3 font-hud text-[9.5px] font-bold tracking-[2px] uppercase transition-all border-b-2 -mb-px",
              isActive
                ? "text-gold border-gold"
                : "text-ink-3 border-transparent hover:text-ink-2",
            ].join(" ")}
          >
            {t === "auto" ? "Auto Trade" : "Copy Trade"}
          </button>
        );
      })}
    </div>
  );
}

function FieldHelper({ text }: { text: string }) {
  return (
    <p className="text-[9px] text-ink-4 font-mono mt-0.5 leading-snug">{text}</p>
  );
}

// Shared input/select style: border-2 by default, gold on focus with soft glow, border-3 when active
const INPUT_CLS =
  "w-full bg-surface border border-border-2 rounded px-2 py-1.5 text-xs font-mono text-ink-1 " +
  "focus:border-gold focus:shadow-[0_0_0_2px_rgba(245,200,66,0.08)] focus:outline-none " +
  "active:border-border-3";

export function CopyTradePage() {
  const { user } = useAuth();
  const api = useMemo(() => makeApi(user?.token ?? null), [user?.token]);
  const [tasks, setTasks] = useState<CopyTask[]>([]);
  const [taskStats, setTaskStats] = useState<Record<string, { pnl_30d?: number; win_rate?: number; total_predictions?: number }>>({});
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
  const [copyTab, setCopyTab] = useState<CopyTab>("manual");
  const [leaderboard, setLeaderboard] = useState<LeaderboardEntry[]>([]);
  const [lbLoading, setLbLoading] = useState(false);
  const [lbOffset, setLbOffset] = useState(0);
  const [lbHasMore, setLbHasMore] = useState(false);
  const [lbLoadingMore, setLbLoadingMore] = useState(false);
  const LB_PAGE_SIZE = 10;

  const load = useCallback(async () => {
    const data = await api.listCopyTasks();
    setTasks(data);
    // Fetch stats for each task (best-effort)
    const statsMap: typeof taskStats = {};
    await Promise.allSettled(
      data.map(async (t: CopyTask) => {
        try {
          const s = await api.getCopyTaskStats(t.id) as { pnl_30d?: number; win_rate?: number; total_predictions?: number };
          statsMap[t.id] = s;
        } catch {
          // non-critical
        }
      })
    );
    setTaskStats(statsMap);
  }, [api]);

  useEffect(() => { void load(); }, [load]);

  // SSE: refresh copy tasks when a copy trade executes or a position changes.
  useSSE(user?.token ?? null, {
    copy_trade_executed: load,
    position_opened: load,
    position_closed: load,
  });

  // 15s polling fallback for SSE stalls.
  useEffect(() => {
    const id = setInterval(load, 15_000);
    return () => clearInterval(id);
  }, [load]);

  const loadLeaderboard = useCallback(async () => {
    setLbLoading(true);
    try {
      const data = await api.getLeaderboard(0, LB_PAGE_SIZE);
      setLeaderboard(data);
      setLbOffset(data.length);
      setLbHasMore(data.length >= LB_PAGE_SIZE);
    } catch {
      // non-critical
    } finally {
      setLbLoading(false);
    }
  }, [api]);

  const loadMoreLeaderboard = useCallback(async () => {
    setLbLoadingMore(true);
    try {
      const page = await api.getLeaderboard(lbOffset, LB_PAGE_SIZE);
      setLbOffset((prev) => prev + page.length);
      setLeaderboard((prev) => {
        const seen = new Set(prev.map((e) => e.wallet));
        const fresh = page.filter((e) => !seen.has(e.wallet));
        return [...prev, ...fresh];
      });
      setLbHasMore(page.length >= LB_PAGE_SIZE);
    } catch {
      // leave lbHasMore unchanged so the button stays and user can retry
    } finally {
      setLbLoadingMore(false);
    }
  }, [api, lbOffset]);

  useEffect(() => {
    if (copyTab === "leaderboard") void loadLeaderboard();
  }, [copyTab, loadLeaderboard]);

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

  const copyTabs: FilterTab<CopyTab>[] = [
    { key: "manual", label: "Manual" },
    { key: "leaderboard", label: "Leaderboard" },
  ];

  const navigate = useNavigate();

  return (
    <>
      <TopBar />
      <PageTabs active="copy" onSwitch={(t) => navigate(t === "auto" ? "/autotrade" : "/autotrade?tab=copy")} />
      <div className="px-3.5 pt-2 pb-6 animate-page-in">

        {/* Page header */}
        <div className="mb-3 mx-0.5">
          <div className="font-hud text-[10px] font-bold tracking-[3px] text-ink-2 uppercase flex items-center gap-2 mb-1.5">
            <span className="w-3 h-px bg-gold" aria-hidden />
            Copy Trade
          </div>
          <p className="text-ink-3 text-xs font-mono leading-relaxed">
            Copy Trade automatically mirrors the trades of top-performing Polymarket traders.
            Add a target wallet, configure your settings, and the bot handles the rest.
          </p>
        </div>

        <FilterTabs tabs={copyTabs} active={copyTab} onChange={setCopyTab} />

        {copyTab === "leaderboard" && (
          <CollapsibleSection id="copytrade_leaderboard" label="Leaderboard">
            <LeaderboardPanel
              entries={leaderboard}
              loading={lbLoading}
              hasMore={lbHasMore}
              loadingMore={lbLoadingMore}
              onLoadMore={() => void loadMoreLeaderboard()}
              api={api}
              onCopyWallet={(w) => { setWallet(w); setCopyTab("manual"); setShowForm(true); }}
            />
          </CollapsibleSection>
        )}

        {copyTab === "manual" && (
        <>
        {/* Active Targets */}
        {tasks.length === 0 && !showForm ? (
          <div className="my-6 p-4 rounded-lg border border-surface-3 bg-surface-1/50 text-center">
            <div className="text-2xl mb-2">🐋</div>
            <p className="font-hud text-sm font-bold text-ink-2 mb-1">No copy targets yet.</p>
            <p className="text-ink-3 text-xs font-mono leading-relaxed">
              Add a Polymarket wallet address below<br />to start mirroring their trades.
            </p>
            <button
              onClick={() => setShowForm(true)}
              className="mt-3 font-hud text-[9px] font-bold tracking-widest text-gold uppercase px-3 py-1.5 rounded border border-gold/40 bg-gold/10 hover:bg-gold/20"
            >
              + Add Target
            </button>
          </div>
        ) : (
          <>
          <CollapsibleSection id="copytrade_targets" label={`Active Targets (${tasks.length})`}>
            <div className="space-y-2 mb-3">
              {tasks.map((t) => {
                const stats = taskStats[t.id];
                return (
                  <div
                    key={t.id}
                    className="p-3 rounded-lg border border-surface-3 bg-surface-1"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <div className="font-hud text-sm font-bold text-ink-1 flex items-center gap-2 flex-wrap">
                          🐋 {t.nickname}
                          <span className={`text-[9px] font-bold tracking-widest uppercase px-1.5 py-0.5 rounded border ${
                            t.status === "active"
                              ? "text-grn border-grn/40 bg-grn/10"
                              : "text-ink-3 border-ink-4/40 bg-surface-2"
                          }`}>
                            {t.status.toUpperCase()}
                          </span>
                        </div>
                        <div className="text-[10px] text-ink-4 mt-0.5">
                          <TxHash hash={t.wallet_address} className="text-[10px]" />
                        </div>
                        <div className="text-[10px] text-ink-3 mt-1 flex gap-2 flex-wrap">
                          <span>{t.copy_direction === "buys_only" ? "📈 Buys only" : "🔄 Buys & Sells"}</span>
                          <span className="text-ink-4">·</span>
                          <span>{t.execution_mode === "auto" ? "⚡ Auto" : "✋ Manual"}</span>
                          <span className="text-ink-4">·</span>
                          <span>{t.allow_topups ? "➕ Top-ups" : "🚫 No top-ups"}</span>
                        </div>
                        {stats && (
                          <div className="mt-1.5 flex gap-3 text-[9px] font-mono">
                            <span className="text-ink-3">
                              Trades: <span className="text-ink-1 font-bold">{stats.total_predictions ?? "—"}</span>
                            </span>
                            <span className="text-ink-3">
                              Est. PnL:{" "}
                              <span className={
                                stats.pnl_30d == null ? "text-ink-1 font-bold" :
                                stats.pnl_30d >= 0 ? "text-grn font-bold" : "text-red font-bold"
                              }>
                                {stats.pnl_30d == null ? "—" : `${stats.pnl_30d >= 0 ? "+" : ""}$${stats.pnl_30d.toFixed(2)}`}
                              </span>
                            </span>
                          </div>
                        )}
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
                );
              })}
            </div>
            {!showForm && (
              <button
                onClick={() => setShowForm(true)}
                className="w-full py-2 rounded border border-gold/30 bg-gold/5 text-gold text-xs font-bold hover:bg-gold/10 font-hud tracking-widest uppercase"
              >
                + Add Target
              </button>
            )}
          </CollapsibleSection>
          </>
        )}

        {/* Add Form */}
        {showForm && (
          <div className="mt-4 p-3 rounded-lg border border-surface-3 bg-surface-1 space-y-3">
            <div className="flex items-center justify-between">
              <div className="font-hud text-[10px] font-bold tracking-[3px] text-ink-2 uppercase flex items-center gap-2">
                <span className="w-3 h-px bg-gold" aria-hidden />
                Add Copy Target
              </div>
              <button
                onClick={() => setShowForm(false)}
                className="text-[9px] font-bold text-ink-3 hover:text-ink-1"
              >
                ← Cancel
              </button>
            </div>

            <div className="space-y-2 md:grid md:grid-cols-2 md:gap-3 md:space-y-0">
              <div>
                <label className="text-[9px] text-ink-4 uppercase block mb-0.5">Wallet Address *</label>
                <input
                  type="text"
                  placeholder="0x..."
                  value={wallet}
                  onChange={e => setWallet(e.target.value)}
                  className={INPUT_CLS}
                />
                <FieldHelper text="Find trader's address on their Polymarket profile → Copy Address" />
              </div>

              <div>
                <label className="text-[9px] text-ink-4 uppercase block mb-0.5">Nickname</label>
                <input
                  type="text"
                  placeholder="Bull Whale"
                  value={nickname}
                  onChange={e => setNickname(e.target.value)}
                  className={INPUT_CLS}
                />
              </div>

              <div>
                <label className="text-[9px] text-ink-4 uppercase block mb-0.5">Copy Direction</label>
                <select
                  value={direction}
                  onChange={e => setDirection(e.target.value as typeof direction)}
                  className={INPUT_CLS}
                >
                  <option value="buys_only">Buys Only</option>
                  <option value="buys_and_sells">Buys & Sells</option>
                </select>
                <FieldHelper text={
                  direction === "buys_only"
                    ? "Copy entries, get notified on exits."
                    : "Fully automated mirror — copies both entries and exits."
                } />
              </div>

              <div>
                <label className="text-[9px] text-ink-4 uppercase block mb-0.5">Copy Type</label>
                <select
                  value={copyType}
                  onChange={e => setCopyType(e.target.value as typeof copyType)}
                  className={INPUT_CLS}
                >
                  <option value="fixed">Fixed $</option>
                  <option value="percentage">Percentage %</option>
                  <option value="rm">RM Mirror</option>
                </select>
                <FieldHelper text={
                  copyType === "fixed"
                    ? "Same dollar amount per trade."
                    : copyType === "percentage"
                    ? "% of your balance (grows with profits)."
                    : "Mirror exact position size scaled by your balance ratio."
                } />
              </div>

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
                  className={INPUT_CLS}
                />
              </div>

              <div>
                <label className="text-[9px] text-ink-4 uppercase block mb-0.5">Slippage</label>
                <select
                  value={slippage}
                  onChange={e => setSlippage(e.target.value as typeof slippage)}
                  className={INPUT_CLS}
                >
                  <option value="5">5%</option>
                  <option value="10">10%</option>
                </select>
                <FieldHelper text="Max price difference accepted when copying. Higher = better fill rate but less precise entry." />
              </div>

              <div>
                <label className="text-[9px] text-ink-4 uppercase block mb-0.5">Execution</label>
                <select
                  value={execMode}
                  onChange={e => setExecMode(e.target.value as typeof execMode)}
                  className={INPUT_CLS}
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
                  className={INPUT_CLS}
                >
                  <option value="yes">Yes</option>
                  <option value="no">No</option>
                </select>
                <FieldHelper text="Follow if the trader buys MORE of the same market later." />
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
        </>
        )}
      </div>
    </>
  );
}

function badgeLabel(badge: string | null): string {
  switch (badge) {
    case "Whale": return "🐋 Whale";
    case "Hot Streak": return "🔥 Hot Streak";
    case "Conservative": return "🛡 Conservative";
    case "High Risk": return "⚡ High Risk";
    default: return badge ?? "";
  }
}

function badgeClass(badge: string | null): string {
  switch (badge) {
    case "Whale": return "text-blue-400 border-blue-400/30 bg-blue-400/10";
    case "Hot Streak": return "text-orange-400 border-orange-400/30 bg-orange-400/10";
    case "Conservative": return "text-green-400 border-green-400/30 bg-green-400/10";
    case "High Risk": return "text-red-400 border-red-400/30 bg-red-400/10";
    default: return "text-ink-3 border-border-2 bg-surface-2";
  }
}

function truncateWallet(wallet: string): string {
  if (wallet.length < 12) return wallet;
  return `${wallet.slice(0, 6)}...${wallet.slice(-4)}`;
}

function Wallet360Panel({
  data,
  loading,
  onCopy,
}: {
  data: Wallet360 | null;
  loading: boolean;
  onCopy: () => void;
}) {
  if (loading) {
    return (
      <div className="mt-2 space-y-1">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-5 rounded bg-surface-2 animate-pulse" />
        ))}
      </div>
    );
  }

  if (!data || !data.available) {
    return (
      <div className="mt-2 p-2 rounded border border-surface-3 bg-surface text-[10px] font-mono text-ink-3">
        Profile data unavailable. You can still copy this wallet.
        <button
          onClick={onCopy}
          className="ml-2 text-[9px] font-bold text-gold px-2 py-0.5 rounded border border-gold/40 bg-gold/10 hover:bg-gold/20"
        >
          Copy Trader
        </button>
      </div>
    );
  }

  const isHighRisk = data.sybil_risk_flag || data.risk_level === "HIGH";

  return (
    <div className="mt-2 p-2 rounded border border-surface-3 bg-surface space-y-1.5">
      {isHighRisk && (
        <div className="px-2 py-1 rounded border border-yellow-500/40 bg-yellow-500/10 text-[10px] font-mono text-yellow-400">
          ⚠️ {data.sybil_risk_flag ? "Sybil risk detected." : ""} {data.risk_level === "HIGH" ? "High risk profile." : ""}
        </div>
      )}
      <div className="grid grid-cols-2 gap-1 text-[9px] font-mono">
        <div className="bg-surface-1 rounded px-1.5 py-1">
          <span className="text-ink-4">Sharpe </span>
          <span className="text-ink-1 font-bold">{data.sharpe_ratio != null ? data.sharpe_ratio.toFixed(2) : "—"}</span>
        </div>
        <div className="bg-surface-1 rounded px-1.5 py-1">
          <span className="text-ink-4">Max DD </span>
          <span className="text-red font-bold">{data.max_drawdown != null ? `${(data.max_drawdown * 100).toFixed(1)}%` : "—"}</span>
        </div>
        <div className="bg-surface-1 rounded px-1.5 py-1">
          <span className="text-ink-4">Markets </span>
          <span className="text-ink-1 font-bold">{data.markets_traded ?? "—"}</span>
        </div>
        <div className="bg-surface-1 rounded px-1.5 py-1">
          <span className="text-ink-4">Trades </span>
          <span className="text-ink-1 font-bold">{data.total_trades ?? "—"}</span>
        </div>
        <div className="bg-surface-1 rounded px-1.5 py-1">
          <span className="text-ink-4">Trend </span>
          <span className="text-ink-1 font-bold">{data.performance_trend ?? "—"}</span>
        </div>
        <div className="bg-surface-1 rounded px-1.5 py-1">
          <span className="text-ink-4">Risk </span>
          <span className={`font-bold ${data.risk_level === "HIGH" ? "text-red" : data.risk_level === "LOW" ? "text-grn" : "text-ink-1"}`}>
            {data.risk_level ?? "—"}
          </span>
        </div>
        <div className="bg-surface-1 rounded px-1.5 py-1 col-span-2">
          <span className="text-ink-4">Sybil </span>
          <span className={`font-bold ${data.sybil_risk_flag ? "text-red" : "text-grn"}`}>
            {data.sybil_risk_flag ? `⚠️ Flagged (score: ${data.sybil_risk_score?.toFixed(2) ?? "?"})` : "Clean"}
          </span>
        </div>
        {data.last_active && (
          <div className="bg-surface-1 rounded px-1.5 py-1 col-span-2">
            <span className="text-ink-4">Last Active </span>
            <span className="text-ink-1 font-bold">{data.last_active}</span>
          </div>
        )}
      </div>
      <button
        onClick={onCopy}
        className="w-full py-1 rounded border border-gold/40 bg-gold/10 text-gold text-[9px] font-bold hover:bg-gold/20"
      >
        Copy Trader
      </button>
    </div>
  );
}

function LeaderboardPanel({
  entries,
  loading,
  hasMore,
  loadingMore,
  onLoadMore,
  api,
  onCopyWallet,
}: {
  entries: LeaderboardEntry[];
  loading: boolean;
  hasMore: boolean;
  loadingMore: boolean;
  onLoadMore: () => void;
  api: ReturnType<typeof makeApi>;
  onCopyWallet: (wallet: string) => void;
}) {
  const [expandedWallet, setExpandedWallet] = useState<string | null>(null);
  const [wallet360Data, setWallet360Data] = useState<Wallet360 | null>(null);
  const [wallet360Loading, setWallet360Loading] = useState(false);

  const handleExpand = useCallback(async (wallet: string) => {
    if (expandedWallet === wallet) {
      setExpandedWallet(null);
      setWallet360Data(null);
      return;
    }
    setExpandedWallet(wallet);
    setWallet360Data(null);
    setWallet360Loading(true);
    try {
      const data = await api.getWallet360(wallet);
      setWallet360Data(data);
    } catch {
      setWallet360Data(null);
    } finally {
      setWallet360Loading(false);
    }
  }, [expandedWallet, api]);

  if (loading) {
    return (
      <div className="space-y-2 mt-2">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-16 rounded-lg border border-surface-3 bg-surface-1 animate-pulse" />
        ))}
      </div>
    );
  }

  if (entries.length === 0) {
    return (
      <div className="my-6 p-4 rounded-lg border border-surface-3 bg-surface-1/50 text-center">
        <div className="text-2xl mb-2">📊</div>
        <p className="font-hud text-sm font-bold text-ink-2 mb-1">No leaderboard data yet.</p>
        <p className="text-ink-3 text-xs font-mono">Trader rankings appear here as copy data accumulates.</p>
      </div>
    );
  }

  return (
    <div className="space-y-2 mt-2">
      <div
        className="px-2.5 py-1.5 text-[8.5px] font-mono text-ink-4 tracking-[1px] border rounded"
        style={{ borderColor: "rgba(255,255,255,0.05)", background: "rgba(255,255,255,0.02)" }}
      >
        Realtime Polymarket data · null fields shown as — · badges from backend only
      </div>
      {entries.map((e) => (
        <div key={e.wallet} className="rounded-lg border border-surface-3 bg-surface-1 overflow-hidden">
          <button
            className="w-full p-3 text-left"
            onClick={() => void handleExpand(e.wallet)}
          >
            <div className="flex items-start justify-between gap-2">
              <div className="flex items-center gap-2 min-w-0 flex-1">
                <span className="text-gold font-bold font-mono text-[11px] flex-shrink-0">#{e.rank}</span>
                <div className="min-w-0">
                  <div className="font-hud text-[11px] font-bold text-ink-1">
                    {e.alias || truncateWallet(e.wallet)}
                  </div>
                  {e.alias && (
                    <div className="text-[9px] font-mono text-ink-4">{truncateWallet(e.wallet)}</div>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-1.5 flex-shrink-0">
                {e.badge && (
                  <span className={`text-[9px] font-bold tracking-widest uppercase px-1.5 py-0.5 rounded border ${badgeClass(e.badge)}`}>
                    {badgeLabel(e.badge)}
                  </span>
                )}
                <span className="text-[9px] text-ink-4">{expandedWallet === e.wallet ? "▲" : "▼"}</span>
              </div>
            </div>

            <div className="mt-2 grid grid-cols-3 gap-1 text-[9px] font-mono">
              <div className="bg-surface rounded px-1.5 py-1">
                <div className="text-ink-4">Win Rate</div>
                <div className="text-ink-1 font-bold">{e.win_rate != null ? `${(e.win_rate * 100).toFixed(0)}%` : "—"}</div>
              </div>
              <div className="bg-surface rounded px-1.5 py-1">
                <div className="text-ink-4">Total PnL</div>
                <div className={`font-bold ${e.total_pnl != null && e.total_pnl >= 0 ? "text-grn" : "text-red"}`}>
                  {e.total_pnl != null ? `${e.total_pnl >= 0 ? "+" : ""}$${e.total_pnl.toFixed(0)}` : "—"}
                </div>
              </div>
              <div className="bg-surface rounded px-1.5 py-1">
                <div className="text-ink-4">ROI</div>
                <div className={`font-bold ${e.roi_pct != null && e.roi_pct >= 0 ? "text-grn" : "text-red"}`}>
                  {e.roi_pct != null ? `${(e.roi_pct * 100).toFixed(1)}%` : "—"}
                </div>
              </div>
            </div>

            <div className="mt-1.5 flex items-center justify-between">
              <span className="text-[9px] font-mono text-ink-4">
                Vol: {e.volume_usdc != null ? `$${(e.volume_usdc / 1000).toFixed(1)}k` : "—"}
              </span>
            </div>
          </button>

          {expandedWallet === e.wallet && (
            <div className="px-3 pb-3">
              <Wallet360Panel
                data={wallet360Data}
                loading={wallet360Loading}
                onCopy={() => onCopyWallet(e.wallet)}
              />
            </div>
          )}
        </div>
      ))}
      {hasMore && (
        <button
          type="button"
          onClick={onLoadMore}
          disabled={loadingMore}
          className="w-full mt-2 py-2 font-hud text-[9px] font-bold tracking-[1.5px] uppercase text-ink-3 border border-border-1 clip-btn transition-colors hover:border-border-2 disabled:opacity-50"
          style={{ background: "rgba(255,255,255,0.02)" }}
        >
          {loadingMore ? "Loading…" : "Load more"}
        </button>
      )}
    </div>
  );
}
