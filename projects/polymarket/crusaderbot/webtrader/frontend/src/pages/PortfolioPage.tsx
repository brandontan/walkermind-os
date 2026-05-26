import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { CollapsibleSection } from "../components/CollapsibleSection";
import { DepositModal } from "../components/DepositModal";
import { DesktopPageHeader } from "../components/DesktopPageHeader";
import { EmptyState } from "../components/EmptyState";
import { FilterTabs, type FilterTab } from "../components/FilterTabs";
import { PositionCard } from "../components/PositionCard";
import { TopBar } from "../components/TopBar";
import { WithdrawModal } from "../components/WithdrawModal";
import {
  makeApi,
  type ChartPoint,
  type OrderItem,
  type PortfolioAnalytics,
  type PortfolioSummary,
  type PositionItem,
} from "../lib/api";
import { useAuth } from "../lib/auth";
import { useSSE } from "../lib/sse";

type Tab = "all" | "open" | "closed" | "orders" | "analytics";
// 7D=1W, 30D=1M in backend; "All" maps to "ALL"
type Period = "1D" | "7D" | "30D" | "All";

const PERIODS: Period[] = ["1D", "7D", "30D", "All"];

// Map UI period labels to backend query params
const PERIOD_API: Record<Period, string> = {
  "1D": "1D",
  "7D": "1W",
  "30D": "1M",
  "All": "ALL",
};

export function PortfolioPage() {
  const { user } = useAuth();
  const api = useMemo(() => makeApi(user?.token ?? null), [user?.token]);
  const CLOSED_PAGE_SIZE = 20;
  const ORDERS_PAGE_SIZE = 20;

  const [open, setOpen] = useState<PositionItem[]>([]);
  const [closed, setClosed] = useState<PositionItem[]>([]);
  const [closedOffset, setClosedOffset] = useState(0);
  const [closedHasMore, setClosedHasMore] = useState(false);
  const [closedLoadingMore, setClosedLoadingMore] = useState(false);
  const [orders, setOrders] = useState<OrderItem[]>([]);
  const [ordersOffset, setOrdersOffset] = useState(0);
  const [ordersHasMore, setOrdersHasMore] = useState(false);
  const [ordersLoadingMore, setOrdersLoadingMore] = useState(false);
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [chartData, setChartData] = useState<ChartPoint[]>([]);
  const [chartPeriod, setChartPeriod] = useState<Period>("7D");
  const [tab, setTab] = useState<Tab>("open");
  const [error, setError] = useState<string | null>(null);

  // Cash Out modal state
  const [cashOutTarget, setCashOutTarget] = useState<PositionItem | null>(null);
  const [cashOutLoading, setCashOutLoading] = useState(false);
  const [cashOutError, setCashOutError] = useState<string | null>(null);

  // Deposit / Withdraw modal state
  const [showDeposit, setShowDeposit] = useState(false);
  const [showWithdraw, setShowWithdraw] = useState(false);
  const [depositAddress, setDepositAddress] = useState<string | null>(null);
  const [isPaperMode, setIsPaperMode] = useState(true);
  const [walletLoading, setWalletLoading] = useState(false);

  const loadPositions = useCallback(async () => {
    try {
      const [o, c, summ] = await Promise.all([
        api.getPositions("open"),
        api.getPositions("closed", CLOSED_PAGE_SIZE, 0),
        api.getPortfolioSummary(),
      ]);
      setOpen(o);
      setClosed(c);
      setClosedOffset(c.length);
      setClosedHasMore(c.length >= CLOSED_PAGE_SIZE);
      setSummary(summ);
    } catch (e) {
      setError(String(e));
    }
  }, [api]);

  const loadOrders = useCallback(async () => {
    try {
      const ords = await api.getOrders(ORDERS_PAGE_SIZE, 0);
      setOrders(ords);
      setOrdersOffset(ords.length);
      setOrdersHasMore(ords.length >= ORDERS_PAGE_SIZE);
    } catch {
      // non-critical — orders list stays stale
    }
  }, [api]);

  const loadMoreClosed = useCallback(async () => {
    setClosedLoadingMore(true);
    try {
      const page = await api.getPositions("closed", CLOSED_PAGE_SIZE, closedOffset);
      setClosedOffset((prev) => prev + page.length);
      setClosed((prev) => {
        const seen = new Set(prev.map((p) => p.id));
        const fresh = page.filter((p) => !seen.has(p.id));
        return [...prev, ...fresh];
      });
      setClosedHasMore(page.length >= CLOSED_PAGE_SIZE);
    } catch {
      // leave closedHasMore unchanged so the button stays and user can retry
    } finally {
      setClosedLoadingMore(false);
    }
  }, [api, closedOffset]);

  const loadMoreOrders = useCallback(async () => {
    setOrdersLoadingMore(true);
    try {
      const page = await api.getOrders(ORDERS_PAGE_SIZE, ordersOffset);
      setOrdersOffset((prev) => prev + page.length);
      setOrders((prev) => {
        const seen = new Set(prev.map((o) => o.id));
        const fresh = page.filter((o) => !seen.has(o.id));
        return [...prev, ...fresh];
      });
      setOrdersHasMore(page.length >= ORDERS_PAGE_SIZE);
    } catch {
      // leave ordersHasMore unchanged so the button stays and user can retry
    } finally {
      setOrdersLoadingMore(false);
    }
  }, [api, ordersOffset]);

  const loadChart = useCallback(
    async (period: Period) => {
      try {
        const data = await api.getPortfolioChart(PERIOD_API[period]);
        setChartData(data);
      } catch {
        // non-critical — chart stays empty
      }
    },
    [api],
  );

  useEffect(() => {
    void loadPositions();
  }, [loadPositions]);

  useEffect(() => {
    void loadChart(chartPeriod);
  }, [loadChart, chartPeriod]);

  useEffect(() => {
    void loadOrders();
  }, [loadOrders]);

  const refresh = useCallback(() => {
    void loadPositions();
    void loadChart(chartPeriod);
    void loadOrders();
  }, [loadPositions, loadChart, loadOrders, chartPeriod]);

  useSSE(user?.token ?? null, {
    positions: refresh,
    position_opened: refresh,
    position_closed: refresh,
    position_updated: refresh,
    portfolio: refresh,
    portfolio_update: refresh,
  });

  // Polling fallback so equity/positions stay fresh even if the SSE stream
  // stalls (reconnect gaps, proxy idle-timeouts). SSE remains the fast path.
  useEffect(() => {
    const id = setInterval(refresh, 15000);
    return () => clearInterval(id);
  }, [refresh]);

  const handleCashOutConfirm = useCallback(async () => {
    if (!cashOutTarget) return;
    setCashOutLoading(true);
    setCashOutError(null);
    try {
      await api.closePosition(cashOutTarget.id);
      setCashOutTarget(null);
      void loadPositions();
      void loadOrders();
    } catch (e) {
      setCashOutError(String(e));
    } finally {
      setCashOutLoading(false);
    }
  }, [api, cashOutTarget, loadPositions, loadOrders]);

  const allPositions = useMemo(() => {
    const combined = [...open, ...closed];
    // Most recent activity on top: closed trades by close time, open by open time.
    const recency = (p: PositionItem) =>
      new Date(p.closed_at ?? p.opened_at).getTime();
    combined.sort((a, b) => recency(b) - recency(a));
    return combined;
  }, [open, closed]);

  const tabs: FilterTab<Tab>[] = [
    { key: "open", label: "Open", count: open.length },
    { key: "closed", label: "Closed", count: closed.length },
    { key: "all", label: "All", count: open.length + closed.length },
    { key: "analytics", label: "Analytics" },
    { key: "orders", label: "Orders", count: orders.length, advanced: true },
  ];

  return (
    <>
      <TopBar />
      <div className="px-3.5 pt-3.5 pb-6 animate-page-in">
        {/* Desktop page header — hidden on mobile */}
        <DesktopPageHeader
          title={<>PORT<span className="text-gold">FOLIO</span></>}
          subtitle="POSITIONS · P&amp;L · TRADE HISTORY"
        />
        {summary && <PortfolioHeader summary={summary} />}

        {/* Deposit / Withdraw on Portfolio money surface */}
        <div className="flex gap-2 mb-3">
          <button
            type="button"
            disabled={walletLoading}
            onClick={async () => {
              if (depositAddress !== null) { setShowDeposit(true); return; }
              setWalletLoading(true);
              try {
                const w = await api.getWallet();
                setDepositAddress(w.deposit_address);
                setIsPaperMode(w.paper_mode !== false);
                setShowDeposit(true);
              } catch {
                // leave depositAddress null so the next click retries
              } finally {
                setWalletLoading(false);
              }
            }}
            className="flex-1 clip-btn font-hud text-[10px] font-bold tracking-[1.5px] uppercase py-2 transition-colors disabled:opacity-50"
            style={{
              background: "rgba(0,255,156,0.08)",
              border: "1px solid rgba(0,255,156,0.3)",
              color: "#00FF9C",
            }}
          >
            {walletLoading ? "…" : "↓ Deposit"}
          </button>
          <button
            type="button"
            disabled={walletLoading}
            onClick={async () => {
              if (depositAddress !== null) { setShowWithdraw(true); return; }
              setWalletLoading(true);
              try {
                const w = await api.getWallet();
                setDepositAddress(w.deposit_address);
                setIsPaperMode(w.paper_mode !== false);
                setShowWithdraw(true);
              } catch {
                // leave depositAddress null so the next click retries
              } finally {
                setWalletLoading(false);
              }
            }}
            className="flex-1 clip-btn font-hud text-[10px] font-bold tracking-[1.5px] uppercase py-2 transition-colors disabled:opacity-50"
            style={{
              background: "rgba(245,200,66,0.06)",
              border: `1px solid rgba(245,200,66,${isPaperMode ? "0.15" : "0.3"})`,
              color: `rgba(245,200,66,${isPaperMode ? "0.45" : "1"})`,
            }}
            title={isPaperMode ? "Withdraw unavailable in Paper Mode" : undefined}
          >
            ↑ Withdraw
          </button>
        </div>

        <PnlChart
          data={chartData}
          period={chartPeriod}
          onPeriodChange={(p) => setChartPeriod(p)}
        />

        {error && <div className="text-red text-sm mb-3">{error}</div>}

        <FilterTabs tabs={tabs} active={tab} onChange={setTab} />

        {tab === "open" && (
          <CollapsibleSection id="portfolio_open_positions" label={`Open Positions (${open.length})`}>
            {open.length === 0 ? (
              <EmptyState
                icon="📭"
                title="No Open Positions"
                text="When auto-trade opens a position, it will appear here in real-time."
              />
            ) : (
              <div className="md:grid md:grid-cols-2 md:gap-3">
                {open.map((p) => (
                  <PositionRow
                    key={p.id}
                    p={p}
                    onCashOut={() => { setCashOutTarget(p); setCashOutError(null); }}
                    onForceRedeem={async () => {
                      try { await api.forceRedeem(p.id); } catch { /* surfaced via refresh */ }
                      refresh();
                    }}
                  />
                ))}
              </div>
            )}
          </CollapsibleSection>
        )}

        {tab === "closed" && (
          <CollapsibleSection id="portfolio_closed_positions" label={`Closed Trades (${closed.length})`}>
            {closed.length === 0 ? (
              <EmptyState
                icon="📦"
                title="No Closed Trades"
                text="Closed trades, expiries, and force-exits land here."
              />
            ) : (
              <>
                <div className="md:grid md:grid-cols-2 md:gap-3">
                  {closed.map((p) => <PositionRow key={p.id} p={p} />)}
                </div>
                {closedHasMore && (
                  <button
                    type="button"
                    onClick={() => void loadMoreClosed()}
                    disabled={closedLoadingMore}
                    className="w-full mt-2 py-2 font-hud text-[9px] font-bold tracking-[1.5px] uppercase text-ink-3 border border-border-1 clip-btn transition-colors hover:border-border-2 disabled:opacity-50"
                    style={{ background: "rgba(255,255,255,0.02)" }}
                  >
                    {closedLoadingMore ? "Loading…" : "Load more"}
                  </button>
                )}
              </>
            )}
          </CollapsibleSection>
        )}

        {tab === "all" && (
          <CollapsibleSection id="portfolio_all_positions" label={`All Positions (${allPositions.length})`}>
            {allPositions.length === 0 ? (
              <EmptyState
                icon="📭"
                title="No Positions"
                text="Your trades will appear here once auto-trade opens a position."
              />
            ) : (
              <div className="md:grid md:grid-cols-2 md:gap-3">
                {allPositions.map((p) => <PositionRow key={p.id} p={p} />)}
              </div>
            )}
          </CollapsibleSection>
        )}

        {tab === "orders" && (
          <CollapsibleSection id="portfolio_orders" label={`Orders (${orders.length})`}>
            {orders.length === 0 ? (
              <EmptyState
                icon="🧾"
                title="No Orders"
                text="Limit orders from auto-trading will appear here."
              />
            ) : (
              <>
                <div className="space-y-2">
                  {orders.map((o) => <OrderRow key={o.id} o={o} />)}
                </div>
                {ordersHasMore && (
                  <button
                    type="button"
                    onClick={() => void loadMoreOrders()}
                    disabled={ordersLoadingMore}
                    className="w-full mt-2 py-2 font-hud text-[9px] font-bold tracking-[1.5px] uppercase text-ink-3 border border-border-1 clip-btn transition-colors hover:border-border-2 disabled:opacity-50"
                    style={{ background: "rgba(255,255,255,0.02)" }}
                  >
                    {ordersLoadingMore ? "Loading…" : "Load more"}
                  </button>
                )}
              </>
            )}
          </CollapsibleSection>
        )}

        {tab === "analytics" && <AnalyticsPanel api={api} />}
      </div>

      {showDeposit && (
        <DepositModal
          address={depositAddress ?? ""}
          paperMode={isPaperMode}
          balance={summary?.available_usdc}
          onClose={() => setShowDeposit(false)}
        />
      )}

      {showWithdraw && (
        <WithdrawModal
          paperMode={isPaperMode}
          balance={summary?.available_usdc ?? 0}
          onClose={() => setShowWithdraw(false)}
          onWithdraw={api.requestWithdrawal}
          onSuccess={() => { setShowWithdraw(false); void loadPositions(); }}
        />
      )}

      {/* Cash Out confirm modal */}
      {cashOutTarget && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center"
          style={{ background: "rgba(0,0,0,0.7)" }}
        >
          <div
            className="bg-surface border border-border-1 clip-card p-5 w-[320px]"
            role="dialog"
            aria-modal="true"
          >
            <p className="font-hud text-[11px] font-bold tracking-[2px] uppercase text-gold mb-3">
              Close Position
            </p>
            <p className="text-xs text-ink-2 font-mono mb-1">
              {cashOutTarget.market_question ?? cashOutTarget.market_id.slice(0, 30)}
            </p>
            <p className="text-[11px] text-ink-3 font-mono mb-4">
              Close at market price?
              {cashOutTarget.current_price != null && (() => {
                const cp = cashOutTarget.current_price!;
                const ep = cashOutTarget.entry_price;
                const est = cashOutTarget.side === "no"
                  ? cashOutTarget.size_usdc * (1 - cp) / Math.max(1 - ep, 0.0001)
                  : cashOutTarget.size_usdc * cp / Math.max(ep, 0.0001);
                return <> Est. fill ≈ ${est.toFixed(2)}</>;
              })()}
            </p>
            {cashOutError && (
              <p className="text-red text-[10px] font-mono mb-3">{cashOutError}</p>
            )}
            <div className="flex gap-2">
              <button
                type="button"
                disabled={cashOutLoading}
                onClick={() => void handleCashOutConfirm()}
                className="flex-1 clip-btn font-hud text-[10px] font-bold tracking-[1.5px] uppercase py-2.5 transition-colors"
                style={{ background: "rgba(255,45,85,0.12)", border: "1px solid rgba(255,45,85,0.4)", color: "#FF2D55" }}
              >
                {cashOutLoading ? "Closing…" : "Confirm"}
              </button>
              <button
                type="button"
                disabled={cashOutLoading}
                onClick={() => setCashOutTarget(null)}
                className="flex-1 clip-btn font-hud text-[10px] font-bold tracking-[1.5px] uppercase py-2.5 transition-colors text-ink-3"
                style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)" }}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

// ── Portfolio Header ──────────────────────────────────────────────────────────────

function PortfolioHeader({ summary }: { summary: PortfolioSummary }) {
  const fmtSigned = (v: number) => {
    const sign = v >= 0 ? "+" : "−";
    return `${sign}$${Math.abs(v).toFixed(2)}`;
  };
  const realizedTone =
    Math.abs(summary.realized_pnl) < 0.005
      ? "text-ink-2"
      : summary.realized_pnl >= 0
        ? "text-grn"
        : "text-red";
  const unrealizedTone =
    Math.abs(summary.unrealized_pnl) < 0.005
      ? "text-ink-2"
      : summary.unrealized_pnl >= 0
        ? "text-grn"
        : "text-red";

  return (
    <div className="mb-3 bg-surface border border-border-1 clip-card p-3.5">
      <div className="flex items-baseline gap-2 mb-3">
        <span className="font-mono text-[9px] text-ink-3 tracking-[2px] uppercase">
          Equity
        </span>
        <span className="font-display text-[30px] text-gold leading-none tracking-[-1px]">
          ${summary.equity_usdc.toFixed(2)}
        </span>
      </div>
      <div className="grid grid-cols-3 gap-x-3 gap-y-0">
        <div className="flex flex-col gap-0.5">
          <span className="font-mono text-[8px] text-ink-3 tracking-[1.5px] uppercase">
            Available
          </span>
          <span className="font-mono text-[13px] text-ink-1 font-semibold">
            ${summary.available_usdc.toFixed(2)}
          </span>
        </div>
        <div className="flex flex-col gap-0.5">
          <span className="font-mono text-[8px] text-ink-3 tracking-[1.5px] uppercase">
            Realized
          </span>
          <span className={`font-mono text-[13px] font-semibold ${realizedTone}`}>
            {Math.abs(summary.realized_pnl) < 0.005
              ? "$0.00"
              : fmtSigned(summary.realized_pnl)}
          </span>
        </div>
        <div className="flex flex-col gap-0.5">
          <span className="font-mono text-[8px] text-ink-3 tracking-[1.5px] uppercase">
            Unrealized
          </span>
          <span
            className={`font-mono text-[13px] font-semibold ${unrealizedTone}`}
          >
            {Math.abs(summary.unrealized_pnl) < 0.005
              ? "$0.00"
              : fmtSigned(summary.unrealized_pnl)}
          </span>
        </div>
      </div>
    </div>
  );
}

// ── P&L Chart ─────────────────────────────────────────────────────────────────

// Custom tooltip: equity + date/time + PnL delta from period start
function ChartTooltip({ active, payload }: { active?: boolean; payload?: Array<{ payload: ChartEntry }> }) {
  if (!active || !payload?.length) return null;
  const entry = payload[0].payload;
  const delta = entry.pnlDelta;
  const sign = delta >= 0 ? "+" : "−";
  const deltaColor = Math.abs(delta) < 0.005 ? "#8FA3C4" : delta >= 0 ? "#00FF9C" : "#FF2D55";
  let dateLabel = entry.ts;
  try {
    dateLabel = new Date(entry.ts).toLocaleString([], {
      month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    });
  } catch { /* leave raw */ }
  return (
    <div style={{
      background: "#0A1628",
      border: "1px solid rgba(245,200,66,0.14)",
      borderRadius: "3px",
      padding: "6px 10px",
      fontFamily: "JetBrains Mono, monospace",
      fontSize: "11px",
      color: "#F0F5FF",
      minWidth: "120px",
    }}>
      <div style={{ color: "#455370", marginBottom: "3px", fontSize: "9px", letterSpacing: "1px" }}>
        {dateLabel}
      </div>
      <div style={{ fontWeight: 600, marginBottom: "2px" }}>
        ${entry.equity.toFixed(2)}
      </div>
      <div style={{ color: deltaColor, fontSize: "10px" }}>
        {Math.abs(delta) < 0.005 ? "±$0.00" : `${sign}$${Math.abs(delta).toFixed(2)}`}
      </div>
    </div>
  );
}

type ChartEntry = { label: string; equity: number; ts: string; pnlDelta: number };

function PnlChart({
  data,
  period,
  onPeriodChange,
}: {
  data: ChartPoint[];
  period: Period;
  onPeriodChange: (p: Period) => void;
}) {
  const startEquity = data.length > 0 ? data[0].equity : 0;
  const chartEntries: ChartEntry[] = data.map((d) => ({
    label: fmtChartTime(d.ts, period),
    equity: d.equity,
    ts: d.ts,
    pnlDelta: d.equity - startEquity,
  }));

  const hasData = data.length >= 2;
  const equities = data.map((d) => d.equity);
  const minEq = hasData ? Math.min(...equities) : 0;
  const maxEq = hasData ? Math.max(...equities) : 100;
  const pad = Math.max((maxEq - minEq) * 0.05, 1);
  const domain: [number, number] = [
    Math.floor(minEq - pad),
    Math.ceil(maxEq + pad),
  ];

  return (
    <div className="mb-3 bg-surface border border-border-1 clip-card overflow-hidden">
      <div className="flex border-b border-border-1">
        {PERIODS.map((p) => (
          <button
            key={p}
            type="button"
            onClick={() => onPeriodChange(p)}
            className={`flex-1 py-[7px] font-hud text-[10px] font-bold tracking-[1.5px] uppercase transition-colors ${
              period === p ? "text-gold" : "text-ink-3 hover:text-ink-2"
            }`}
            style={
              period === p
                ? {
                    background: "rgba(245,200,66,0.08)",
                    boxShadow: "inset 0 1px 0 var(--gold,#F5C842)",
                  }
                : undefined
            }
          >
            {p}
          </button>
        ))}
      </div>
      <div className="h-[128px] px-1 pt-2 pb-1">
        {!hasData ? (
          <div className="h-full flex items-center justify-center font-mono text-[11px] text-ink-3">
            No trade history for this period
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart
              data={chartEntries}
              margin={{ top: 2, right: 6, left: 0, bottom: 0 }}
            >
              <defs>
                <linearGradient id="pnlGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#F5C842" stopOpacity={0.22} />
                  <stop offset="100%" stopColor="#F5C842" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid
                horizontal={true}
                vertical={false}
                stroke="rgba(245,200,66,0.06)"
              />
              <XAxis
                dataKey="label"
                tick={{
                  fill: "#455370",
                  fontSize: 8,
                  fontFamily: "monospace",
                }}
                axisLine={false}
                tickLine={false}
                interval="preserveStartEnd"
              />
              <YAxis
                domain={domain}
                tick={{
                  fill: "#455370",
                  fontSize: 8,
                  fontFamily: "monospace",
                }}
                axisLine={false}
                tickLine={false}
                width={44}
                tickFormatter={(v: number) => `$${v.toFixed(0)}`}
              />
              <Tooltip content={<ChartTooltip />} />
              <Area
                type="monotone"
                dataKey="equity"
                stroke="#F5C842"
                strokeWidth={1.5}
                fill="url(#pnlGrad)"
                dot={false}
                activeDot={{
                  r: 3,
                  fill: "#F5C842",
                  stroke: "#0A1628",
                  strokeWidth: 1.5,
                }}
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}

// ── Position Row ──────────────────────────────────────────────────────────────

const EXIT_LABEL: Record<string, string> = {
  tp_hit: "TP",
  sl_hit: "SL",
  manual: "MNL",
  strategy_exit: "STRAT",
  resolution: "RES",
  force_close: "FORCE",
  close_failed: "ERR",
  market_expired: "EXP",
};

const EXIT_TONE: Record<string, string> = {
  tp_hit: "text-grn",
  sl_hit: "text-red",
  manual: "text-ink-2",
  strategy_exit: "text-cyan",
  resolution: "text-ink-2",
  force_close: "text-gold",
  close_failed: "text-red",
  market_expired: "text-ink-3",
};

// Human-readable "Closed by" reason for the expandable trade detail.
const EXIT_FULL_LABEL: Record<string, string> = {
  tp_hit: "Take Profit (TP)",
  sl_hit: "Stop Loss (SL)",
  resolution: "Market Resolution",
  resolution_win: "Market Resolution (Won)",
  resolution_loss: "Market Resolution (Lost)",
  market_expired: "Expired Time",
  manual: "Manual Close",
  strategy_exit: "Strategy Exit",
  force_close: "Force Close",
  close_failed: "Close Failed",
};

// Preset display names for the strategy that opened the trade
// (positions.strategy_type holds the underlying strategy class; map it to the
// preset name the user actually selected, e.g. late_entry_v3 → "Close Sweep").
const STRATEGY_LABEL: Record<string, string> = {
  late_entry_v3: "Close Sweep",
  confluence_scalper: "Crypto Scalper",
  trend_breakout: "Trend Breakout",
  momentum: "Contrarian",
  value_investor: "Value Hunter",
  copy_trade: "Whale Mirror",
  signal: "Signal Sniper",
  signal_following: "Signal Following",
  pair_arb: "Pair Arb",
  ensemble: "Smart Mix",
};

function fmtStrategy(s?: string | null): string | null {
  if (!s) return null;
  return STRATEGY_LABEL[s] ?? s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function PositionRow({ p, onCashOut, onForceRedeem, defaultExpanded }: {
  p: PositionItem;
  onCashOut?: () => void;
  onForceRedeem?: () => void;
  defaultExpanded?: boolean;
}) {
  const isOpen = p.status === "open";
  const awaitingRedeem = isOpen && !!p.awaiting_redeem;
  // A won-pending position has no meaningful "unavailable" price — it settles
  // at the redeem payout regardless of the live mark.
  const priceUnavailable = isOpen && !awaitingRedeem && p.current_price === null;

  const curVal = (() => {
    if (awaitingRedeem) {
      // Confirmed win awaiting redemption: value at the $1.00/share payout
      // (shares = size / entry), not the live mark — the live mark can sit
      // below entry and misreport a settled win as a loss.
      return p.entry_price > 0 ? p.size_usdc / p.entry_price : p.size_usdc;
    }
    if (isOpen) {
      const price = p.current_price ?? p.entry_price;
      return p.entry_price > 0
        ? (price / p.entry_price) * p.size_usdc
        : p.size_usdc;
    }
    return p.size_usdc + (p.pnl_usdc ?? 0);
  })();

  const diff = isOpen ? curVal - p.size_usdc : (p.pnl_usdc ?? 0);
  const tone: "zero" | "up" | "dn" =
    priceUnavailable ? "zero" : Math.abs(diff) < 0.005 ? "zero" : diff > 0 ? "up" : "dn";

  const pnlSign = diff >= 0 ? "+" : "−";
  const pnlPct =
    p.size_usdc > 0 ? (Math.abs(diff) / p.size_usdc) * 100 : 0;
  const pnlStr = priceUnavailable
    ? "—"
    : Math.abs(diff) < 0.005
      ? "±$0.00"
      : `${pnlSign}$${Math.abs(diff).toFixed(2)} (${pnlPct.toFixed(1)}%)`;

  const side: "yes" | "no" | "exp" =
    p.status === "expired" ? "exp" : p.side === "no" ? "no" : "yes";

  const exitKey = p.exit_reason ?? "";
  const exitLabel = EXIT_LABEL[exitKey];
  const exitToneClass = EXIT_TONE[exitKey] ?? "text-ink-3";

  const pnlToneClass =
    tone === "zero" ? "text-ink-2" : tone === "up" ? "text-grn" : "text-red";

  const strategyLabel = fmtStrategy(p.strategy_type);

  const metaItems = [
    ...(strategyLabel
      ? [
          <span key="strat" className="text-ink-4 uppercase tracking-wide">
            {strategyLabel}
          </span>,
        ]
      : []),
    <span key="cost" className="text-ink-3">
      <span className="text-ink-4 text-[8px]">IN</span> ${p.size_usdc.toFixed(2)}
    </span>,
    // Entry price — essential context for any open position
    ...(isOpen && !awaitingRedeem && p.entry_price > 0
      ? [
          <span key="entry" className="text-ink-2">
            {p.side.toUpperCase()} @ {(p.entry_price * 100).toFixed(1)}¢
          </span>,
        ]
      : []),
    ...(awaitingRedeem
      ? [
          <span key="won" className="font-bold text-grn">
            WON · AWAITING REDEEM
          </span>,
        ]
      : []),
    <span key="pnl" className={pnlToneClass}>
      {pnlStr}
    </span>,
    ...(exitLabel
      ? [
          <span key="exit" className={`font-bold ${exitToneClass}`}>
            {exitLabel}
          </span>,
        ]
      : []),
    <span key="time">
      {isOpen ? "LIVE" : fmtDate(p.closed_at ?? p.opened_at)}
    </span>,
  ];

  // Expandable trade detail. Exit time/price stay blank ("—") while the
  // position is open; they fill in once the close is confirmed.
  const detail = (
    <div>
      {strategyLabel ? <DetailRow label="Strategy" value={strategyLabel} tone="text-cyan" /> : null}
      <DetailRow label="Entry Time" value={fmtDateTime(p.opened_at)} />
      <DetailRow label="Entry Price" value={`${p.side.toUpperCase()} @ ${fmtCents(p.entry_price)}`} />
      <DetailRow label="Exit Time" value={isOpen ? "—" : fmtDateTime(p.closed_at)} />
      <DetailRow label="Exit Price" value={isOpen ? "—" : fmtCents(p.current_price)} />
      <DetailRow label="TP Price" value={fmtCents(p.tp_price)} tone="text-grn" />
      <DetailRow label="SL Price" value={fmtCents(p.sl_price)} tone="text-red" />
      {!isOpen && p.exit_reason ? (
        <DetailRow
          label="Closed By"
          value={EXIT_FULL_LABEL[p.exit_reason] ?? p.exit_reason}
          tone={EXIT_TONE[p.exit_reason] ?? "text-ink-1"}
        />
      ) : null}
    </div>
  );

  return (
    <PositionCard
      market={p.market_question ?? `${p.market_id.slice(0, 18)}…`}
      positionValue={{ value: priceUnavailable ? "—" : `$${curVal.toFixed(2)}`, tone }}
      side={side}
      borderTone={tone}
      meta={metaItems}
      metaAdvanced={[]}
      detail={detail}
      defaultExpanded={defaultExpanded}
      footer={
        awaitingRedeem && onForceRedeem ? (
          <button
            type="button"
            onClick={onForceRedeem}
            className="w-full mt-2 clip-btn font-hud text-[9px] font-bold tracking-[1.5px] uppercase py-2 transition-colors"
            style={{
              background: "rgba(0,255,156,0.08)",
              border: "1px solid rgba(0,255,156,0.35)",
              color: "var(--grn, #00FF9C)",
            }}
          >
            ⚡ Force Redeem
          </button>
        ) : isOpen && onCashOut ? (
          <button
            type="button"
            onClick={onCashOut}
            className="w-full mt-2 clip-btn font-hud text-[9px] font-bold tracking-[1.5px] uppercase py-2 transition-colors"
            style={diff > 0 ? {
              background: "rgba(0,255,156,0.08)",
              border: "1px solid rgba(0,255,156,0.35)",
              color: "var(--grn, #00FF9C)",
            } : {
              background: "rgba(255,45,85,0.08)",
              border: "1px solid rgba(255,45,85,0.35)",
              color: "var(--red, #FF6B6B)",
            }}
          >
            {diff > 0 ? "💚 Cash Out" : "🔴 Cash Out"}
          </button>
        ) : undefined
      }
    />
  );
}

// ── Order Row ────────────────────────────────────────────────────────────────

const ORDER_STATUS_BADGE: Record<string, { label: string; color: string }> = {
  partial_filled: { label: "PARTIAL", color: "#F5C842" },
  filled:         { label: "FILLED",  color: "#00FF9C" },
  cancelled:      { label: "CANCEL",  color: "#FF2D55" },
  failed:         { label: "FAILED",  color: "#FF2D55" },
  pending:        { label: "PENDING", color: "#8FA3C4" },
  submitted:      { label: "OPEN",    color: "#8FA3C4" },
};

function OrderRow({ o }: { o: OrderItem }) {
  const badge = ORDER_STATUS_BADGE[o.status] ?? { label: o.status.toUpperCase(), color: "#8FA3C4" };
  const filledPct = o.size_usdc > 0 && o.filled_amount > 0
    ? Math.min((o.filled_amount / o.size_usdc) * 100, 100)
    : 0;
  const remaining = o.remaining_amount ?? (o.size_usdc - o.filled_amount);

  return (
    <div className="bg-surface border border-border-1 clip-card p-3">
      <div className="flex items-center justify-between mb-1.5">
        <span className="font-mono text-[10px] text-ink-2 truncate max-w-[200px]">
          {o.market_question ?? o.market_id.slice(0, 20)}
        </span>
        <span
          className="font-hud text-[9px] font-bold tracking-[1.5px] px-1.5 py-0.5 rounded"
          style={{ color: badge.color, background: `${badge.color}18`, border: `1px solid ${badge.color}40` }}
        >
          {badge.label}
        </span>
      </div>

      <div className="flex items-center gap-3 text-[10px] font-mono text-ink-3 mb-2">
        <span className="uppercase font-bold" style={{ color: o.side === "yes" ? "#00FF9C" : "#FF2D55" }}>
          {o.side}
        </span>
        <span>${o.size_usdc.toFixed(2)} @ {(o.price * 100).toFixed(1)}¢</span>
        <span className="text-ink-4">{o.mode}</span>
      </div>

      {o.status === "partial_filled" || o.filled_amount > 0 ? (
        <div>
          <div className="flex justify-between text-[9px] font-mono text-ink-3 mb-1">
            <span>Filled: <span className="text-grn">${o.filled_amount.toFixed(2)}</span> / ${o.size_usdc.toFixed(2)}</span>
            <span>Remaining: ${Math.max(remaining, 0).toFixed(2)}</span>
          </div>
          <div className="h-1 rounded-full overflow-hidden" style={{ background: "rgba(255,255,255,0.06)" }}>
            <div
              className="h-full rounded-full transition-all"
              style={{ width: `${filledPct.toFixed(1)}%`, background: "#00FF9C" }}
            />
          </div>
        </div>
      ) : null}
    </div>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtChartTime(ts: string, period: Period): string {
  try {
    const d = new Date(ts);
    if (period === "1D")
      return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    if (period === "7D" || period === "30D")
      return d.toLocaleDateString([], { month: "short", day: "numeric" });
    return d.toLocaleDateString([], { month: "short", year: "2-digit" });
  } catch {
    return ts.slice(0, 10);
  }
}

function fmtDate(ts: string): string {
  try {
    return new Date(ts).toLocaleDateString([], {
      month: "short",
      day: "numeric",
    });
  } catch {
    return ts.slice(0, 10);
  }
}

function fmtDateTime(ts: string | null | undefined): string {
  if (!ts) return "—";
  try {
    return new Date(ts).toLocaleString([], {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return ts;
  }
}

function fmtCents(price: number | null | undefined): string {
  return price == null ? "—" : `${(price * 100).toFixed(1)}¢`;
}

// One label/value row inside the expandable trade detail panel.
function DetailRow({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="flex justify-between gap-3 py-0.5 font-mono text-[10px]">
      <span className="text-ink-3 uppercase tracking-[1px]">{label}</span>
      <span className={tone ?? "text-ink-1"}>{value}</span>
    </div>
  );
}

// ── Analytics Panel ────────────────────────────────────────────────────────────────

function AnalyticsPanel({ api }: { api: ReturnType<typeof makeApi> }) {
  const [data, setData] = useState<PortfolioAnalytics | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api.getPortfolioAnalytics()
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [api]);

  if (loading) {
    return (
      <div className="space-y-2 mt-2">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-14 rounded-lg border border-surface-3 bg-surface-1 animate-pulse" />
        ))}
      </div>
    );
  }

  if (!data || !data.has_data) {
    return (
      <div className="my-6 p-4 rounded-lg border border-surface-3 bg-surface-1/50 text-center">
        <div className="text-2xl mb-2">📊</div>
        <p className="font-hud text-sm font-bold text-ink-2 mb-1">No analytics yet.</p>
        <p className="text-ink-3 text-xs font-mono leading-relaxed">
          No closed trades yet. Analytics appear after your first completed position.
        </p>
      </div>
    );
  }

  // Max drawdown is only meaningful once equity has moved through multiple trades.
  // 100% drawdown from a single expired position is misleading — suppress it.
  const settledTrades = data.wins + data.losses;
  const drawdownValue = data.max_drawdown_pct != null && settledTrades >= 2
    ? `${data.max_drawdown_pct.toFixed(1)}%`
    : settledTrades < 2 ? "Not enough data" : "—";
  const drawdownColor = data.max_drawdown_pct != null && data.max_drawdown_pct > 10 && settledTrades >= 2
    ? "var(--red,#FF2D55)"
    : "var(--ink-1)";

  // Win/loss ratio: only show when there are actual settled (non-expired) trades.
  const ratioValue = settledTrades > 0 && data.win_loss_ratio != null
    ? `${data.win_loss_ratio.toFixed(2)}`
    : settledTrades === 0 ? "Not enough data" : "—";

  return (
    <div className="space-y-3 mt-2">
      <div className="text-[9px] font-mono text-ink-4 tracking-[1.5px] uppercase mb-1">
        Settled trades only · market_expired excluded
      </div>
      {/* Row 1: key metrics */}
      <div className="grid grid-cols-2 gap-2">
        <AnalyticCard
          label="Max Drawdown"
          value={drawdownValue}
          color={drawdownColor}
        />
        <AnalyticCard
          label="Win / Loss Ratio"
          value={ratioValue}
          sub={settledTrades > 0 ? `${data.wins}W · ${data.losses}L` : undefined}
          color="var(--ink-1)"
        />
        <AnalyticCard
          label="Avg Hold Duration"
          value={data.avg_hold_hours != null ? `${data.avg_hold_hours.toFixed(1)}h` : "—"}
          color="var(--ink-1)"
        />
        <AnalyticCard
          label="Best Trade"
          value={data.best_trade != null ? `${data.best_trade.pnl_usdc >= 0 ? "+" : ""}$${data.best_trade.pnl_usdc.toFixed(2)}` : "—"}
          sub={data.best_trade?.market_question?.slice(0, 30) ?? undefined}
          color="var(--grn,#00FF9C)"
        />
      </div>

      {/* Worst trade */}
      {data.worst_trade && (
        <div className="p-3 rounded-lg border border-surface-3 bg-surface-1">
          <div className="text-[9px] font-mono text-ink-4 uppercase tracking-widest mb-1">Worst Trade</div>
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-mono text-ink-2 truncate max-w-[200px]">
              {data.worst_trade.market_question ?? "—"}
            </span>
            <span className="font-bold font-mono text-[11px] text-red flex-shrink-0">
              ${data.worst_trade.pnl_usdc.toFixed(2)}
            </span>
          </div>
        </div>
      )}

      {/* Profit per strategy */}
      {data.profit_per_strategy.length > 0 && (
        <div className="p-3 rounded-lg border border-surface-3 bg-surface-1">
          <div className="text-[9px] font-mono text-ink-4 uppercase tracking-widest mb-2">Profit by Strategy</div>
          <div className="space-y-1.5">
            {data.profit_per_strategy.map((s) => (
              <div key={s.strategy} className="flex items-center justify-between">
                <span className="text-[10px] font-mono text-ink-2 capitalize">{s.strategy}</span>
                <span className={`font-bold font-mono text-[10px] ${s.pnl_usdc >= 0 ? "text-grn" : "text-red"}`}>
                  {s.pnl_usdc >= 0 ? "+" : ""}${s.pnl_usdc.toFixed(2)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function AnalyticCard({
  label,
  value,
  sub,
  color,
}: {
  label: string;
  value: string;
  sub?: string;
  color: string;
}) {
  return (
    <div className="p-3 rounded-lg border border-surface-3 bg-surface-1">
      <div className="text-[9px] font-mono text-ink-4 uppercase tracking-widest mb-1">{label}</div>
      <div className="font-hud font-bold text-[14px] leading-tight" style={{ color }}>{value}</div>
      {sub && <div className="text-[9px] font-mono text-ink-4 mt-0.5 truncate">{sub}</div>}
    </div>
  );
}
