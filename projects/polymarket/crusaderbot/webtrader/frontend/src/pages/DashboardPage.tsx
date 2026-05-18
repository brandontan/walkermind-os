import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AdvancedOnly } from "../components/AdvancedGate";
import { DesktopPageHeader } from "../components/DesktopPageHeader";
import { HeroCard, type RiskLevel } from "../components/HeroCard";
import { KillSwitchButton } from "../components/KillSwitchButton";
import { StatCard } from "../components/StatCard";
import { StatsGrid } from "../components/StatsGrid";
import { Terminal, type TerminalLine } from "../components/Terminal";
import { Ticker } from "../components/Ticker";
import { TopBar } from "../components/TopBar";
import { useAlertCenter } from "../App";
import { makeApi, type AlertItem, type DashboardSummary, type FeedSignal } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useSSE } from "../lib/sse";

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
  const [feedSignals, setFeedSignals] = useState<FeedSignal[]>([]);
  const [feedOffset, setFeedOffset] = useState(0);
  const [feedHasMore, setFeedHasMore] = useState(false);
  const [feedLoadingMore, setFeedLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastTick, setLastTick] = useState<number | null>(null);
  // Alerts come from the global AlertCenterContext (fetched once at AppShell level)
  const { alerts: ctxAlerts } = useAlertCenter();
  const alerts: AlertItem[] = ctxAlerts.slice(0, 5);

  const load = useCallback(async () => {
    try {
      const summary = await api.getDashboard();
      setData(summary);
    } catch (e) {
      setError(String(e));
    }
  }, [api]);

  const FEED_PAGE_SIZE = 10;

  const loadFeedSignals = useCallback(async () => {
    try {
      const data = await api.getRecentSignals(FEED_PAGE_SIZE, 0);
      setFeedSignals(data);
      setFeedOffset(data.length);
      setFeedHasMore(data.length >= FEED_PAGE_SIZE);
    } catch { /* silent */ }
  }, [api]);

  const loadMoreFeedSignals = useCallback(async () => {
    setFeedLoadingMore(true);
    try {
      const page = await api.getRecentSignals(FEED_PAGE_SIZE, feedOffset);
      setFeedOffset((prev) => prev + page.length);
      setFeedSignals((prev) => {
        const seen = new Set(prev.map((s) => `${s.market_id}-${s.published_at}`));
        const fresh = page.filter((s) => !seen.has(`${s.market_id}-${s.published_at}`));
        return [...prev, ...fresh];
      });
      setFeedHasMore(page.length >= FEED_PAGE_SIZE);
    } catch {
      // leave feedHasMore unchanged so the button stays and user can retry
    } finally {
      setFeedLoadingMore(false);
    }
  }, [api, feedOffset]);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => { void loadFeedSignals(); }, [loadFeedSignals]);

  useSSE(user?.token ?? null, {
    positions:        () => void load(),
    portfolio:        () => void load(),
    system:           () => void load(),
    settings:         () => void load(),
    position_opened:  () => void load(),
    position_closed:  () => void load(),
    portfolio_update: () => void load(),
    scanner_tick: (raw) => {
      void load();
      void loadFeedSignals();
      const payload = raw as { ts?: number };
      if (payload.ts) setLastTick(payload.ts * 1000);
    },
  });

  if (error) return (
    <>
      <TopBar />
      <div className="p-4 text-red text-sm">{error}</div>
    </>
  );
  if (!data) return (
    <>
      <TopBar tradingMode="paper" />
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

  const modeLabel = data.trading_mode === "live" ? "LIVE" : "PAPER MODE";

  return (
    <>
      <TopBar tradingMode={data.trading_mode} />
      <div className="px-3.5 pt-3.5 pb-6 animate-page-in">

        {/* Paper Mode reassurance — visible on trading pages when not in live mode */}
        {data.trading_mode !== "live" && (
          <div
            className="mb-3 px-3 py-2 flex items-center gap-2 text-[10px] font-mono font-bold tracking-[1.5px] clip-card border"
            style={{
              background: "rgba(245,200,66,0.04)",
              borderColor: "rgba(245,200,66,0.15)",
              color: "var(--gold,#F5C842)",
            }}
            role="status"
          >
            <span style={{ fontSize: "12px" }}>🛡</span>
            PAPER MODE — No real funds at risk
          </div>
        )}

        {/* Desktop page header — hidden on mobile */}
        <DesktopPageHeader
          title={<>DASH<span className="text-gold">BOARD</span></>}
          subtitle={`${modeLabel} · ${data.active_preset ? (presetCode ?? "STRATEGY") + " ACTIVE" : "STRATEGY IDLE"} · EDGE-FINDER`}
        />

        <AdvancedOnly>
          <Ticker items={[
            { symbol: "SIGNAL FEED", value: data.active_preset ? (presetCode ?? "STRATEGY") : "MARKET WATCH", delta: data.active_preset ? "● ACTIVE" : "● MONITORING", dir: "up" },
            { symbol: "SCANNER",     value: `${alerts.length} ALERTS`, delta: alerts.length > 0 ? "● SIGNALS" : "● WATCHING", dir: alerts.length > 0 ? "up" : "neutral" },
            { symbol: "MODE",        value: data.trading_mode === "live" ? "LIVE" : "PAPER", delta: data.trading_mode === "live" ? "● ARMED" : "● SAFE", dir: data.trading_mode === "live" ? "up" : "neutral" },
            { symbol: "GUARDS",      value: data.trading_mode === "live" ? "ARMED" : "LOCKED", delta: data.kill_switch_active ? "● HALTED" : "● READY", dir: data.kill_switch_active ? "dn" : "neutral" },
          ]} />
        </AdvancedOnly>

        {data.kill_switch_active && (
          <div className="mb-3 px-3 py-2.5 text-center text-red text-[13px] font-semibold clip-card border"
            style={{ background: "rgba(255,45,85,0.08)", borderColor: "rgba(255,45,85,0.3)" }}
          >
            ⛔ Kill Switch Active — trading halted
          </div>
        )}

        {/* Desktop: 2-column grid — Left: Hero + Stats | Right: Scanner + Activity */}
        <div className="md:grid md:grid-cols-1 lg:grid-cols-2 md:gap-5 md:items-start min-w-0 overflow-x-hidden">

          {/* LEFT COLUMN: Hero card + Stats */}
          <div className="md:min-w-0 md:overflow-hidden">
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
                    sub={data.trading_mode === "live" ? "Live Mode" : "Paper Mode"}
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
          </div>

          {/* RIGHT COLUMN: Scanner terminal + Recent Activity */}
          <div className="md:min-w-0 md:overflow-hidden">
            <AdvancedOnly>
              <Terminal lines={buildScannerLines(alerts, data, lastTick)} />
            </AdvancedOnly>

            <div className="flex items-center justify-between mt-3.5 mb-2 mx-0.5 md:mt-0">
              <div className="font-hud text-[10px] font-bold tracking-[3px] text-ink-2
                              uppercase flex items-center gap-2">
                <span className="w-3 h-px bg-gold" aria-hidden />
                Live Market Feed
              </div>
              <span className="font-mono text-[9px] text-ink-4">
                signals · sse push
              </span>
            </div>

            {feedSignals.length === 0 ? (
              <div className="text-[12px] text-ink-3 px-1 py-3 font-mono">
                Awaiting signals…
              </div>
            ) : (
              <>
                {feedSignals.map((s) => (
                  <div key={`${s.market_id}-${s.published_at}`} className="p-2.5 mb-1.5 rounded-lg border border-surface-3
                                          bg-surface-1 flex items-center gap-2.5">
                    <span className={`flex-shrink-0 font-hud text-[9px] font-bold px-1.5 py-0.5
                                     rounded border tracking-widest uppercase
                                     ${s.side === "YES"
                                       ? "text-grn border-grn/30 bg-grn/10"
                                       : "text-red border-red/30 bg-red/10"}`}>
                      {s.side}
                    </span>
                    <div className="flex-1 min-w-0">
                      <p className="font-hud text-[10px] font-bold text-ink-1 leading-snug truncate">
                        {s.market_question}
                      </p>
                      <p className="font-mono text-[9px] text-ink-4 mt-0.5">
                        {s.target_price ? `${(s.target_price * 100).toFixed(1)}¢` : "—"}
                        {" · "}
                        {new Date(s.published_at).toLocaleTimeString([], {
                          hour: "2-digit", minute: "2-digit"
                        })}
                      </p>
                    </div>
                    <span className="flex-shrink-0 font-mono text-[9px] text-gold">
                      SIGNAL
                    </span>
                  </div>
                ))}
                {feedHasMore && (
                  <button
                    type="button"
                    onClick={() => void loadMoreFeedSignals()}
                    disabled={feedLoadingMore}
                    className="w-full mt-2 py-2 font-hud text-[9px] font-bold tracking-[1.5px] uppercase text-ink-3 border border-border-1 clip-btn transition-colors hover:border-border-2 disabled:opacity-50"
                    style={{ background: "rgba(255,255,255,0.02)" }}
                  >
                    {feedLoadingMore ? "Loading…" : "Load more"}
                  </button>
                )}
              </>
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
        </div>
      </div>
    </>
  );
}

function buildScannerLines(alerts: AlertItem[], data: DashboardSummary, lastTick: number | null): TerminalLine[] {
  const tickLabel = lastTick
    ? new Date(lastTick).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })
    : "—";
  return [
    {
      parts: [
        { type: "cmd",  text: "market_signal_scanner" },
        { type: "ok",   text: " ✓ ok" },
      ],
    },
    {
      parts: [
        { type: "out",  text: "scanning markets " },
        { type: "warn", text: data.open_positions > 0 ? `${data.open_positions} open` : "monitoring markets" },
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
        { type: "out", text: "last_tick " },
        { type: "ok",  text: tickLabel },
      ],
    },
    {
      parts: [
        { type: "out", text: data.kill_switch_active ? "kill_switch ARMED " : data.open_positions > 0 ? "managing open positions" : "awaiting signal" },
      ],
      cursor: true,
    },
  ];
}
