import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AdvancedOnly } from "../components/AdvancedGate";
import { DesktopPageHeader } from "../components/DesktopPageHeader";
import { EmptyState } from "../components/EmptyState";
import { HeroCard, type RiskLevel } from "../components/HeroCard";
import { KillSwitchButton } from "../components/KillSwitchButton";
import { StatCard } from "../components/StatCard";
import { StatsGrid } from "../components/StatsGrid";
import { Terminal, type TerminalLine } from "../components/Terminal";
import { Ticker } from "../components/Ticker";
import { PositionCarousel } from "../components/PositionCarousel";
import { MarketFeed } from "../components/MarketFeed";
import { TopBar } from "../components/TopBar";
import { useAlertCenter } from "../App";
import { makeApi, type AlertItem, type DashboardSummary, type MarketFeedItem, type PositionItem } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useSSE } from "../lib/sse";
import { PositionRow } from "./PortfolioPage";

const PRESET_CODE: Record<string, string> = {
  close_sweep:  "CANDLE",
  safe_close:   "CANDLE·SAFE",
  flip_hunter:  "CANDLE·FLIP",
};

export function DashboardPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const api = useMemo(() => makeApi(user?.token ?? null), [user?.token]);
  const [data, setData] = useState<DashboardSummary | null>(null);
  const [openPositions, setOpenPositions] = useState<PositionItem[]>([]);
  const [marketFeed, setMarketFeed] = useState<MarketFeedItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [lastTick, setLastTick] = useState<number | null>(null);
  const [lastSignals, setLastSignals] = useState<number>(0);
  const [recentClosed, setRecentClosed] = useState<PositionItem[]>([]);
  const [pnlFlash, setPnlFlash] = useState<"up" | "down" | null>(null);
  // Alerts come from the global AlertCenterContext (fetched once at AppShell level)
  const { alerts: ctxAlerts } = useAlertCenter();
  const alerts: AlertItem[] = ctxAlerts.slice(0, 5);

  // Won-but-not-yet-redeemed positions are settled outcomes pending payout, not
  // live trades — surface them in a dedicated "Awaiting Redeem" strip so the
  // Open Positions list reflects only positions still exposed to the market.
  const liveOpen = useMemo(
    () => openPositions.filter((p) => !p.awaiting_redeem),
    [openPositions],
  );
  const awaitingRedeem = useMemo(
    () => openPositions.filter((p) => p.awaiting_redeem),
    [openPositions],
  );

  const load = useCallback(async () => {
    try {
      const summary = await api.getDashboard();
      setData(summary);
    } catch (e) {
      setError(String(e));
    }
  }, [api]);

  const loadOpenPositions = useCallback(async () => {
    try {
      setOpenPositions(await api.getPositions("open"));
    } catch { /* silent */ }
  }, [api]);

  const loadMarketFeed = useCallback(async () => {
    try {
      setMarketFeed(await api.getMarketFeed());
    } catch { /* silent — feed is non-critical */ }
  }, [api]);

  const loadRecentClosed = useCallback(async () => {
    try {
      setRecentClosed(await api.getPositions("closed", 5));
    } catch { /* silent */ }
  }, [api]);

  const refreshAll = useCallback(() => {
    void load();
    void loadOpenPositions();
    void loadMarketFeed();
    void loadRecentClosed();
  }, [load, loadOpenPositions, loadMarketFeed, loadRecentClosed]);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => { void loadOpenPositions(); }, [loadOpenPositions]);

  useEffect(() => { void loadMarketFeed(); }, [loadMarketFeed]);

  useEffect(() => { void loadRecentClosed(); }, [loadRecentClosed]);

  const { connected: sseConnected } = useSSE(user?.token ?? null, {
    positions:        refreshAll,
    portfolio:        refreshAll,
    system:           () => void load(),
    settings:         () => void load(),
    position_opened:  refreshAll,
    position_closed: (raw) => {
      refreshAll();
      const p = raw as { pnl_usdc?: number };
      setPnlFlash(typeof p.pnl_usdc === "number" && p.pnl_usdc >= 0 ? "up" : "down");
    },
    position_updated: refreshAll,
    portfolio_update: refreshAll,
    scanner_tick: (raw) => {
      refreshAll();
      const payload = raw as { ts?: number; signals?: number };
      if (payload.ts) setLastTick(payload.ts * 1000);
      if (typeof payload.signals === "number") setLastSignals(payload.signals);
    },
  });

  // Polling fallback so the dashboard stays fresh even if the SSE stream
  // stalls (reconnect gaps, proxy idle-timeouts). SSE remains the fast path.
  useEffect(() => {
    const id = setInterval(refreshAll, 15000);
    return () => clearInterval(id);
  }, [refreshAll]);

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
  // Use the actual risk_profile from the backend — not a hardcoded preset map.
  const risk: RiskLevel | null = data.auto_trade_on
    ? (data.risk_profile as RiskLevel ?? "balanced")
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

        {/* Paper mode indicator lives in TopBar StatusPill — no banner needed here */}

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

        <MarketFeed items={marketFeed} />

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
              flashDir={pnlFlash}
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
                    sparkline={[data.pnl_today, data.pnl_7d, data.pnl_alltime]}
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
                    sparkline={[data.pnl_today, data.pnl_7d, data.pnl_alltime]}
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
              <Terminal lines={buildScannerLines(data, lastTick, lastSignals)} />
            </AdvancedOnly>

            {/* Scanner status strip — visible to all users */}
            <div className="mt-3 mb-2 mx-0.5 md:mt-0 px-2.5 py-1.5 rounded-lg border border-surface-3 bg-surface-1 flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <span
                  className={data.auto_trade_on ? "animate-status-pulse" : ""}
                  style={{
                    display: "inline-block", width: "6px", height: "6px", borderRadius: "50%",
                    background: data.auto_trade_on ? "var(--grn,#00FF9C)" : "var(--ink-3,#455370)",
                    boxShadow: data.auto_trade_on ? "0 0 5px var(--grn,#00FF9C)" : "none",
                  }}
                  aria-label={data.auto_trade_on ? "scanner active" : "scanner idle"}
                />
                <span className="font-hud text-[9px] uppercase tracking-[1.5px] text-ink-3">Scanner</span>
              </div>
              <div className="flex items-center gap-3 font-mono text-[9px]">
                <span>
                  <span className="text-ink-4">last </span>
                  <span className="text-ink-1">
                    {lastTick
                      ? new Date(lastTick).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })
                      : "—"}
                  </span>
                </span>
                <span>
                  <span className={(data.signals_today ?? 0) > 0 ? "text-grn font-bold" : "text-ink-3"}>
                    {data.signals_today ?? 0}
                  </span>
                  <span className="text-ink-4"> today</span>
                </span>
                {lastSignals > 0 && (
                  <span>
                    <span className="text-ink-1">{lastSignals}</span>
                    <span className="text-ink-4"> cands</span>
                  </span>
                )}
              </div>
            </div>

            <div className="flex items-center justify-between mt-3.5 mb-2 mx-0.5 md:mt-0">
              <div className="font-hud text-[10px] font-bold tracking-[3px] text-ink-2
                              uppercase flex items-center gap-2">
                <span className="w-3 h-px bg-gold" aria-hidden />
                Open Positions ({liveOpen.length})
              </div>
              <span className="font-mono text-[9px] text-ink-4 flex items-center gap-1.5">
                <span
                  className={sseConnected ? "animate-status-pulse" : ""}
                  style={{
                    display: "inline-block",
                    width: "6px",
                    height: "6px",
                    borderRadius: "50%",
                    background: sseConnected ? "var(--grn,#00FF9C)" : "var(--ink-3,#455370)",
                    boxShadow: sseConnected ? "0 0 6px var(--grn,#00FF9C)" : "none",
                  }}
                  aria-label={sseConnected ? "live" : "reconnecting"}
                />
                {sseConnected ? "live" : "reconnecting…"}
              </span>
            </div>

            {liveOpen.length === 0 ? (
              <EmptyState
                icon="◈"
                title="No Open Positions"
                text="Scanner watching markets"
              />
            ) : (
              <PositionCarousel>
                {liveOpen.map((p) => (
                  <PositionRow key={p.id} p={p} defaultExpanded />
                ))}
              </PositionCarousel>
            )}

            {awaitingRedeem.length > 0 && (
              <>
                <div className="flex items-center justify-between mt-4 mb-2 mx-0.5">
                  <div className="font-hud text-[10px] font-bold tracking-[3px] text-grn
                                  uppercase flex items-center gap-2">
                    <span className="w-3 h-px bg-grn" aria-hidden />
                    Awaiting Redeem ({awaitingRedeem.length})
                  </div>
                  <span className="font-mono text-[9px] text-ink-4">
                    won · settle
                  </span>
                </div>
                {awaitingRedeem.map((p) => (
                  <PositionRow
                    key={p.id}
                    p={p}
                    onForceRedeem={async () => {
                      try { await api.forceRedeem(p.id); } catch { /* surfaced via refresh */ }
                      refreshAll();
                    }}
                  />
                ))}
              </>
            )}

            {recentClosed.length > 0 && (
              <RecentActivityCarousel items={recentClosed} />
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

const RECENT_EXIT_LABEL: Record<string, string> = {
  tp_hit:          "TP",
  sl_hit:          "SL",
  market_expired:  "EXP",
  resolution_win:  "WIN",
  resolution_loss: "LOSS",
  force_close:     "FORCE",
  manual:          "MANUAL",
};

function RecentActivityCarousel({ items }: { items: PositionItem[] }) {
  const [idx, setIdx] = useState(0);

  useEffect(() => {
    if (items.length <= 1) return;
    const t = setInterval(() => setIdx((i) => (i + 1) % items.length), 3500);
    return () => clearInterval(t);
  }, [items.length]);

  const p = items[idx];
  const pnl = p.pnl_usdc ?? 0;
  const isPos = pnl > 0.005;
  const isNeg = pnl < -0.005;
  const pnlClass = isPos ? "text-grn" : isNeg ? "text-red" : "text-ink-3";
  const stripe = isPos ? "var(--grn,#00FF9C)" : isNeg ? "var(--red,#FF2D55)" : "var(--ink-3,#455370)";

  return (
    <div className="mt-4">
      <div className="font-hud text-[10px] font-bold tracking-[3px] text-ink-2 uppercase flex items-center gap-2 mb-2 mx-0.5">
        <span className="w-3 h-px bg-ink-3" aria-hidden />
        Recent Activity
      </div>
      {/* card */}
      <div
        className="relative p-2 pl-3.5 rounded-lg border border-surface-3 bg-surface-1 overflow-hidden cursor-pointer select-none"
        onClick={() => setIdx((i) => (i + 1) % items.length)}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") setIdx((i) => (i + 1) % items.length); }}
        aria-label={`Recent activity ${idx + 1} of ${items.length}`}
      >
        <span className="absolute left-0 top-0 bottom-0 w-0.5" style={{ background: stripe }} aria-hidden />
        <div className="flex items-start justify-between gap-2">
          <p className="text-[9px] font-mono text-ink-4 truncate leading-tight flex-1 min-w-0">
            {p.market_question ?? p.market_id}
          </p>
          <span className="text-[8px] font-mono text-ink-4 whitespace-nowrap flex-shrink-0">
            {RECENT_EXIT_LABEL[p.exit_reason ?? ""] ?? "—"}
          </span>
        </div>
        <div className="flex items-center gap-3 mt-1">
          <span className={`text-[13px] font-bold font-mono leading-none ${pnlClass}`}>
            {pnl >= 0 ? "+" : "−"}${Math.abs(pnl).toFixed(2)}
          </span>
          <span className={`text-[8px] font-hud uppercase ${p.side === "yes" ? "text-grn" : "text-red"}`}>
            {p.side.toUpperCase()}
          </span>
        </div>
      </div>
      {/* dot indicators */}
      {items.length > 1 && (
        <div className="flex justify-center gap-1 mt-1.5">
          {items.map((_, i) => (
            <button
              key={i}
              onClick={() => setIdx(i)}
              aria-label={`Go to item ${i + 1}`}
              className={`rounded-full transition-all ${
                i === idx
                  ? "w-3.5 h-1.5 bg-ink-2"
                  : "w-1.5 h-1.5 bg-surface-4"
              }`}
            />
          ))}
        </div>
      )}
    </div>
  );
}


function buildScannerLines(data: DashboardSummary, lastTick: number | null, lastSignals: number): TerminalLine[] {
  const tickLabel = lastTick
    ? new Date(lastTick).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })
    : "—";
  const signalText = lastSignals > 0 ? `${lastSignals} candidates` : "scanning…";
  return [
    {
      parts: [
        { type: "cmd",  text: "market_signal_scanner" },
        { type: "ok",   text: " ✓ ok" },
      ],
    },
    {
      parts: [
        { type: "out",  text: "mode " },
        { type: "warn", text: data.trading_mode?.toUpperCase() ?? "PAPER" },
        { type: "dim",  text: "  preset " },
        { type: "ok",   text: data.active_preset ?? "—" },
      ],
    },
    {
      parts: [
        { type: "out",  text: "last_tick " },
        { type: "ok",   text: tickLabel },
        { type: "dim",  text: "  signals " },
        { type: lastSignals > 0 ? "ok" : "dim", text: signalText },
      ],
    },
    {
      parts: [
        { type: "out", text: data.kill_switch_active ? "kill_switch " : data.open_positions > 0 ? "managing " : "status " },
        { type: data.kill_switch_active ? "warn" : data.open_positions > 0 ? "ok" : "dim",
          text: data.kill_switch_active ? "ARMED" : data.open_positions > 0 ? `${data.open_positions} open` : "awaiting signal" },
      ],
      cursor: true,
    },
  ];
}
