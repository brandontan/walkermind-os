import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { KillSwitchButton } from "../components/KillSwitchButton";
import { PnLCard } from "../components/PnLCard";
import { makeApi, type DashboardSummary } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useSSE } from "../lib/sse";

const RISK_BADGE: Record<string, string> = {
  safe:       "text-green bg-green/10 border-green/20",
  balanced:   "text-yellow bg-yellow/10 border-yellow/20",
  aggressive: "text-red bg-red/10 border-red/20",
};

export function DashboardPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const api = makeApi(user?.token ?? null);
  const [data, setData] = useState<DashboardSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await api.getDashboard());
    } catch (e) {
      setError(String(e));
    }
  }, [user?.token]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { void load(); }, [load]);

  // SSE: refresh on relevant events
  useSSE(user?.token ?? null, {
    positions: () => void load(),
    portfolio: () => void load(),
    system:    () => void load(),
    settings:  () => void load(),
  });

  if (error) return <div className="p-4 text-red text-sm">{error}</div>;
  if (!data)  return <div className="p-4 text-muted text-sm">Loading…</div>;

  const riskClass = RISK_BADGE[data.active_preset?.split("_")[0] ?? "balanced"] ?? RISK_BADGE.balanced;
  const winRate = data.total_trades > 0
    ? ((data.wins / data.total_trades) * 100).toFixed(1) + "%"
    : "—";
  const pnlSign = data.pnl_today >= 0 ? "+" : "";

  return (
    <div className="pb-24 px-4">
      {/* Header */}
      <div className="flex items-center justify-between pt-6 pb-4">
        <h1 className="text-xl font-bold text-primary">Dashboard</h1>
        <div className="flex items-center gap-2">
          <span className={`text-xs px-2 py-0.5 rounded-full border font-medium uppercase ${
            data.trading_mode === "live" ? "text-green bg-green/10 border-green/30" : "text-muted bg-muted/10 border-border"
          }`}>
            {data.trading_mode}
          </span>
          <span className="text-muted text-xl">🔔</span>
        </div>
      </div>

      {/* Kill switch banner */}
      {data.kill_switch_active && (
        <div className="mb-4 bg-red/10 border border-red/30 rounded-xl p-3 text-red text-sm text-center font-medium">
          ⛔ Kill Switch Active — trading halted
        </div>
      )}

      {/* Hero card */}
      <div className="bg-card border border-border rounded-2xl p-5 mb-4">
        <div className="flex items-center gap-2 mb-3">
          <span className="w-2 h-2 rounded-full bg-green animate-pulse" />
          <span className="text-muted text-xs uppercase tracking-wide">Bot Running</span>
          {data.active_preset && (
            <span className={`text-xs px-2 py-0.5 rounded-full border font-medium ml-auto ${riskClass}`}>
              {data.active_preset.replace("_", " ").toUpperCase()}
            </span>
          )}
        </div>
        <p className="text-3xl font-bold text-primary">${data.equity_usdc.toFixed(2)}</p>
        <p className="text-muted text-xs mt-1">
          Equity ·{" "}
          <span className={data.pnl_today >= 0 ? "text-green" : "text-red"}>
            {pnlSign}${Math.abs(data.pnl_today).toFixed(2)} today
          </span>
        </p>
        <div className="flex gap-3 mt-4">
          <button
            onClick={() => navigate("/autotrade")}
            className="flex-1 py-2 text-sm font-semibold rounded-lg bg-amber text-bg hover:bg-amber/90 transition-colors"
          >
            Configure Strategy
          </button>
          <button
            onClick={() => navigate("/portfolio")}
            className="flex-1 py-2 text-sm font-semibold rounded-lg border border-border text-muted hover:border-amber hover:text-amber transition-colors"
          >
            View Portfolio
          </button>
        </div>
      </div>

      {/* Stat grid */}
      <div className="grid grid-cols-2 gap-3 mb-4">
        <PnLCard label="Balance" value={data.balance_usdc} colorize={false} />
        <PnLCard label="Today PnL" value={data.pnl_today} />
        <div className="bg-card border border-border rounded-xl p-4">
          <p className="text-muted text-xs uppercase tracking-wide mb-1">Win Rate</p>
          <p className="text-xl font-semibold text-primary">{winRate}</p>
        </div>
        <div className="bg-card border border-border rounded-xl p-4">
          <p className="text-muted text-xs uppercase tracking-wide mb-1">Open Positions</p>
          <p className="text-xl font-semibold text-primary">{data.open_positions}</p>
        </div>
      </div>

      {/* Kill switch */}
      <KillSwitchButton
        active={data.kill_switch_active}
        onKill={async () => {
          await api.postKill();
          await load();
        }}
      />
    </div>
  );
}
