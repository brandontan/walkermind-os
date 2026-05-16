import { useCallback, useEffect, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { KillSwitchButton } from "../components/KillSwitchButton";
import { PnLCard } from "../components/PnLCard";
import { makeApi, type AlertItem, type DashboardSummary, type PositionItem } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useSSE } from "../lib/sse";

const RISK_BADGE: Record<string, { label: string; color: string }> = {
  safe:       { label: "SAFE",      color: "text-green bg-green/10 border-green/20" },
  balanced:   { label: "BALANCED",  color: "text-gold  bg-gold/10  border-gold/20"  },
  aggressive: { label: "HIGH RISK", color: "text-red   bg-red/10   border-red/20"   },
};

const PRESET_RISK: Record<string, string> = {
  signal_sniper: "safe",
  whale_mirror:  "balanced",
  hybrid:        "balanced",
  full_auto:     "balanced",
  value_hunter:  "aggressive",
};

function presetRisk(preset: string | null): string {
  if (!preset) return "balanced";
  return PRESET_RISK[preset] ?? "balanced";
}

export function DashboardPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const api = makeApi(user?.token ?? null);
  const [data, setData] = useState<DashboardSummary | null>(null);
  const [openPositions, setOpenPositions] = useState<PositionItem[]>([]);
  const [latestAlert, setLatestAlert] = useState<AlertItem | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [summary, positions, alerts] = await Promise.all([
        api.getDashboard(),
        api.getPositions("open"),
        api.getAlerts(),
      ]);
      setData(summary);
      setOpenPositions(positions.slice(0, 2));
      setLatestAlert(alerts[0] ?? null);
    } catch (e) {
      setError(String(e));
    }
  }, [user?.token]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { void load(); }, [load]);

  useSSE(user?.token ?? null, {
    positions: () => void load(),
    portfolio: () => void load(),
    system:    () => void load(),
    settings:  () => void load(),
  });

  if (error) return <div className="p-4 text-red text-sm">{error}</div>;
  if (!data)  return <div className="p-4 text-muted text-sm">Loading…</div>;

  const riskKey  = presetRisk(data.active_preset);
  const badge    = RISK_BADGE[riskKey] ?? RISK_BADGE.balanced;
  const winRate  = data.total_trades > 0
    ? ((data.wins / data.total_trades) * 100).toFixed(1) + "%"
    : "—";
  const pnlSign  = data.pnl_today >= 0 ? "+" : "";
  const pnlColor = data.pnl_today >= 0 ? "text-green" : "text-red";

  return (
    <div className="pb-28 px-4 animate-page-in">
      {/* Topbar */}
      <div className="flex items-center justify-between pt-6 pb-4">
        <div className="flex items-center gap-2">
          <img
            src="/crusaderbot-logo.png"
            alt="CrusaderBot"
            width={32}
            height={32}
            style={{ objectFit: "contain", filter: "drop-shadow(0 0 8px rgba(245,200,66,0.5))" }}
          />
          <span className="font-bold text-lg text-primary tracking-tight">CrusaderBot</span>
          <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-green/25 bg-green/10 text-green text-xs font-medium">
            <span className="w-1.5 h-1.5 rounded-full bg-green animate-status-pulse" />
            LIVE
          </span>
          <span className="px-2 py-0.5 rounded-full border border-gold/25 bg-gold/10 text-gold text-xs font-medium">
            PAPER
          </span>
        </div>
        <span className="text-muted text-xl select-none">🔔</span>
      </div>

      {/* Kill switch banner */}
      {data.kill_switch_active && (
        <div className="mb-4 bg-red/10 border border-red/30 rounded-2xl p-3 text-red text-sm text-center font-medium">
          ⛔ Kill Switch Active — trading halted
        </div>
      )}

      {/* Hero card */}
      <div className="bg-surface border border-border rounded-2xl p-5 mb-4">
        <div className="flex items-center gap-2 mb-3 flex-wrap">
          <span className="w-2 h-2 rounded-full bg-green animate-status-pulse shrink-0" />
          <span className="text-muted text-xs uppercase tracking-wider">Strategy Active</span>
          {data.active_preset && (
            <span className={`text-xs px-2.5 py-0.5 rounded-full border font-medium ml-auto ${badge.color}`}>
              {badge.label}
            </span>
          )}
        </div>
        <p className="text-4xl font-bold text-primary font-mono">${data.equity_usdc.toFixed(2)}</p>
        <p className="text-muted text-sm mt-1">
          Equity ·{" "}
          <span className={pnlColor}>
            {pnlSign}${Math.abs(data.pnl_today).toFixed(2)} today
          </span>
        </p>
        <div className="flex gap-3 mt-5">
          <button
            onClick={() => navigate("/autotrade")}
            className="flex-1 py-2.5 text-sm font-semibold rounded-button bg-gold text-bg hover:bg-gold/90 active:scale-95 transition-all"
          >
            Configure Strategy
          </button>
          <button
            onClick={() => navigate("/portfolio")}
            className="flex-1 py-2.5 text-sm font-semibold rounded-button border border-border text-muted hover:border-gold hover:text-gold transition-colors"
          >
            Portfolio
          </button>
        </div>
      </div>

      {/* 2×2 stat grid */}
      <div className="grid grid-cols-2 gap-3 mb-4">
        <PnLCard label="Balance"   value={data.balance_usdc} colorize={false} accentColor="#4D9EFF" />
        <PnLCard label="Today PnL" value={data.pnl_today}                    accentColor={data.pnl_today >= 0 ? "#00D68F" : "#FF4D6A"} />
        <div className="bg-card border border-border rounded-xl p-4 overflow-hidden relative">
          <span className="absolute top-0 left-0 right-0" style={{ height: "2px", background: "#F5C842" }} />
          <p className="text-muted text-xs uppercase tracking-wide mb-1">Win Rate</p>
          <p className="text-xl font-semibold font-mono text-primary">{winRate}</p>
        </div>
        <div className="bg-card border border-border rounded-xl p-4 overflow-hidden relative">
          <span className="absolute top-0 left-0 right-0" style={{ height: "2px", background: "#4D9EFF" }} />
          <p className="text-muted text-xs uppercase tracking-wide mb-1">Open</p>
          <p className="text-xl font-semibold font-mono text-primary">{data.open_positions}</p>
        </div>
      </div>

      {/* Scanner ticker card */}
      <div className="bg-card border border-border rounded-2xl p-4 mb-4">
        <div className="flex items-start gap-3">
          <span className="text-xl shrink-0">📡</span>
          <div className="min-w-0 flex-1">
            <p className="text-xs text-muted uppercase tracking-wide mb-1">Scanner</p>
            {latestAlert ? (
              <>
                <p className="text-sm text-primary truncate">{latestAlert.title}</p>
                <p className="text-xs text-muted mt-0.5">
                  {new Date(String(latestAlert.created_at)).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                </p>
              </>
            ) : (
              <p className="text-sm text-muted">No active alerts</p>
            )}
          </div>
        </div>
      </div>

      {/* Open positions preview */}
      {openPositions.length > 0 && (
        <div className="bg-card border border-border rounded-2xl p-4 mb-4">
          <div className="flex items-center justify-between mb-3">
            <p className="text-sm font-semibold text-primary">Open Positions</p>
            <NavLink to="/portfolio" className="text-xs text-gold hover:text-gold/80 transition-colors">
              View all →
            </NavLink>
          </div>
          <div className="space-y-3">
            {openPositions.map((p) => {
              const pnl = p.pnl_usdc ?? 0;
              return (
                <div key={p.id} className="flex items-center justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm text-primary truncate">
                      {p.market_question ?? p.market_id.slice(0, 18) + "…"}
                    </p>
                    <div className="flex items-center gap-1.5 mt-0.5">
                      <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${p.side === "yes" ? "text-green bg-green/10" : "text-red bg-red/10"}`}>
                        {p.side.toUpperCase()}
                      </span>
                      <span className="text-xs px-1.5 py-0.5 rounded font-medium text-blue bg-blue/10">OPEN</span>
                    </div>
                  </div>
                  <p className={`text-sm font-semibold font-mono shrink-0 ${pnl >= 0 ? "text-green" : "text-red"}`}>
                    {pnl >= 0 ? "+" : ""}${Math.abs(pnl).toFixed(2)}
                  </p>
                </div>
              );
            })}
          </div>
        </div>
      )}

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
