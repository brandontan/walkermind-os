import { useCallback, useEffect, useMemo, useState } from "react";
import { AdvancedOnly } from "../components/AdvancedGate";
import { HeroCard, type RiskLevel } from "../components/HeroCard";
import { KillSwitchButton } from "../components/KillSwitchButton";
import { PositionCard } from "../components/PositionCard";
import { StatCard } from "../components/StatCard";
import { StatsGrid } from "../components/StatsGrid";
import { Terminal, type TerminalLine } from "../components/Terminal";
import { Ticker } from "../components/Ticker";
import { TopBar } from "../components/TopBar";
import { makeApi, type AlertItem, type DashboardSummary, type PositionItem } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useSSE } from "../lib/sse";
import { useNavigate, NavLink } from "react-router-dom";

const PRESET_RISK: Record<string, RiskLevel> = {
  signal_sniper: "safe",
  whale_mirror:  "balanced",
  hybrid:        "balanced",
  full_auto:     "balanced",
  value_hunter:  "aggressive",
};

const PRESET_CODE: Record<string, string> = {
  signal_sniper: "SIG",
  whale_mirror:  "CPY",
  hybrid:        "SIG·CPY",
  full_auto:     "SIG·CPY·VAL",
  value_hunter:  "VAL",
};

export function DashboardPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const api = useMemo(() => makeApi(user?.token ?? null), [user?.token]);
  const [data, setData] = useState<DashboardSummary | null>(null);
  const [closedRecent, setClosedRecent] = useState<PositionItem[]>([]);
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [summary, closed, alertList] = await Promise.all([
        api.getDashboard(),
        api.getPositions("closed"),
        api.getAlerts(),
      ]);
      setData(summary);
      setClosedRecent(closed.slice(0, 3));
      setAlerts(alertList.slice(0, 5));
    } catch (e) {
      setError(String(e));
    }
  }, [api]);

  useEffect(() => { void load(); }, [load]);

  useSSE(user?.token ?? null, {
    positions: () => void load(),
    portfolio: () => void load(),
    system:    () => void load(),
    settings:  () => void load(),
  });

  if (error) return (
    <>
      <TopBar />
      <div className="p-4 text-red text-sm">{error}</div>
    </>
  );
  if (!data) return (
    <>
      <TopBar />
      <div className="p-4 text-ink-3 text-sm font-mono">Loading…</div>
    </>
  );

  const presetKey = data.active_preset ?? "";
  const risk: RiskLevel | null = data.active_preset
    ? (PRESET_RISK[presetKey] ?? "balanced")
    : null;
  const presetCode = data.active_preset ? PRESET_CODE[presetKey] : undefined;

  const equityWhole = Math.floor(data.equity_usdc);
  const equityCents = `.${(data.equity_usdc - equityWhole).toFixed(2).slice(2)}`;

  const pnlSign = data.pnl_today >= 0 ? "+" : "-";
  const pnlAbs = Math.abs(data.pnl_today).toFixed(2);
  const pnlZero = Math.abs(data.pnl_today) < 0.005;

  const closedCount = data.total_trades;
  const winRate = data.total_trades > 0
    ? `${((data.wins / data.total_trades) * 100).toFixed(0)}%`
    : "—";

  return (
    <>
      <TopBar notifCount={alerts.length} />
      <div className="px-3.5 pt-3.5 pb-6 animate-page-in">

        <AdvancedOnly>
          <Ticker items={[
            { symbol: "SIGNAL FEED", value: "EDGE-FINDER", delta: "● ACTIVE", dir: "up" },
            { symbol: "SCANNER",     value: `${alerts.length} ALERTS`, delta: "● SYNC", dir: "up" },
            { symbol: "EXIT WATCH",  value: "90s TICK", delta: "● OK", dir: "up" },
            { symbol: "GUARDS",      value: data.trading_mode === "live" ? "ARMED" : "LOCKED", delta: data.trading_mode === "live" ? "● LIVE" : "● PAPER", dir: data.trading_mode === "live" ? "up" : "neutral" },
          ]} />
        </AdvancedOnly>

        {data.kill_switch_active && (
          <div className="mb-3 px-3 py-2.5 text-center text-red text-[13px] font-semibold clip-card border"
            style={{ background: "rgba(255,45,85,0.08)", borderColor: "rgba(255,45,85,0.3)" }}
          >
            ⛔ Kill Switch Active — trading halted
          </div>
        )}

        <HeroCard
          label="Equity"
          value={equityWhole}
          cents={equityCents}
          statusLabel={data.active_preset ? "STRATEGY ACTIVE" : "STRATEGY IDLE"}
          statusCode={presetCode ? <AdvancedOnly>{presetCode}</AdvancedOnly> : undefined}
          risk={risk}
          metaItems={
            <>
              <span className={pnlZero ? "text-ink-2 font-bold inline-flex items-center gap-1" : data.pnl_today >= 0 ? "text-grn font-bold inline-flex items-center gap-1" : "text-red font-bold inline-flex items-center gap-1"}>
                <span aria-hidden>{pnlZero ? "─" : data.pnl_today >= 0 ? "▲" : "▼"}</span>
                {pnlSign}${pnlAbs} TODAY
              </span>
              <span className="text-ink-4">│</span>
              <span>{data.open_positions} OPEN</span>
              <AdvancedOnly>
                <span className="text-ink-4">│</span>
                <span>{closedCount} CLOSED</span>
              </AdvancedOnly>
            </>
          }
          ctaPrimary={{ label: "Configure", onClick: () => navigate("/autotrade") }}
          ctaSecondary={{ label: "Portfolio", onClick: () => navigate("/portfolio") }}
        />

        <StatsGrid
          essential={
            <>
              <StatCard
                color="grn"
                icon="▰"
                label="Balance"
                value={data.balance_usdc.toLocaleString("en-US", { maximumFractionDigits: 0 })}
                unit="USDC"
                sub="Paper Mode"
              />
              <StatCard
                color="gold"
                icon="▱"
                label="Open"
                value={data.open_positions}
                sub={data.open_positions === 0 ? "No positions" : `${data.open_positions} active`}
              />
            </>
          }
          advanced={
            <>
              <StatCard
                large
                color="grn"
                icon="▰"
                label="Balance"
                value={data.balance_usdc.toLocaleString("en-US", { maximumFractionDigits: 0 })}
                unit="USDC"
                sub={`${data.trading_mode === "live" ? "Live" : "Paper"} · Polygon`}
              />
              <StatCard
                color="gold"
                icon="▱"
                label="Win Rate"
                value={winRate}
                sub={`${data.wins}/${data.total_trades} closed`}
              />
              <StatCard
                color="cyan"
                icon="◈"
                label="Signals"
                value={alerts.length}
                sub="last fetch"
                subTone="up"
              />
            </>
          }
        />

        <AdvancedOnly>
          <Terminal lines={buildScannerLines(alerts, data)} />
        </AdvancedOnly>

        <div className="flex items-center justify-between mt-3.5 mb-2 mx-0.5">
          <div className="font-hud text-[10px] font-bold tracking-[3px] text-ink-2 uppercase flex items-center gap-2">
            <span className="w-3 h-px bg-gold" aria-hidden />
            Recent Activity
          </div>
          <NavLink
            to="/portfolio"
            className="font-mono text-[10px] text-gold cursor-pointer tracking-[1px] font-semibold"
          >
            View all →
          </NavLink>
        </div>

        {closedRecent.length === 0 ? (
          <div className="text-[12px] text-ink-3 px-1 py-3 font-mono">
            No closed trades yet.
          </div>
        ) : (
          closedRecent.map((p) => (
            <PositionCard
              key={p.id}
              market={p.market_question ?? `${p.market_id.slice(0, 16)}…`}
              pnl={pnlFor(p)}
              side={positionSide(p)}
              meta={[
                <>${p.size_usdc.toFixed(2)}</>,
                <>{formatTime(p.closed_at ?? p.opened_at)}</>,
              ]}
              metaAdvanced={[
                <>{p.side.toUpperCase()} @ {(p.entry_price * 100).toFixed(1)}¢</>,
              ]}
            />
          ))
        )}

        <div className="mt-4">
          <KillSwitchButton
            active={data.kill_switch_active}
            onKill={async () => {
              await api.postKill();
              await load();
            }}
          />
        </div>
      </div>
    </>
  );
}

function pnlFor(p: PositionItem): { value: string; tone: "zero" | "up" | "dn" } {
  const v = p.pnl_usdc ?? 0;
  if (Math.abs(v) < 0.005) return { value: "$0.00", tone: "zero" };
  const sign = v >= 0 ? "+" : "−";
  return { value: `${sign}$${Math.abs(v).toFixed(2)}`, tone: v >= 0 ? "up" : "dn" };
}

function positionSide(p: PositionItem): "yes" | "no" | "exp" {
  if (p.status === "expired") return "exp";
  return p.side === "no" ? "no" : "yes";
}

function formatTime(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return ts.slice(11, 16);
  }
}

function buildScannerLines(alerts: AlertItem[], data: DashboardSummary): TerminalLine[] {
  const lines: TerminalLine[] = [
    {
      parts: [
        { type: "cmd",  text: "market_signal_scanner" },
        { type: "ok",   text: " ✓ ok" },
      ],
    },
    {
      parts: [
        { type: "out",  text: "scanning markets " },
        { type: "warn", text: data.open_positions > 0 ? `${data.open_positions} open` : "(idle)" },
      ],
    },
    {
      parts: [
        { type: "out",  text: "published " },
        { type: "warn", text: `${alerts.length} signals` },
        { type: "dim",  text: " (edge_finder)" },
      ],
    },
    {
      parts: [
        { type: "out", text: "exit_watch " },
        { type: "ok",  text: "✓ active" },
      ],
    },
    {
      parts: [
        { type: "out", text: data.kill_switch_active ? "kill_switch ARMED " : "awaiting next tick" },
      ],
      cursor: true,
    },
  ];
  return lines;
}
