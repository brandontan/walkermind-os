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
import { DesktopPageHeader } from "../components/DesktopPageHeader";
import { EmptyState } from "../components/EmptyState";
import { FilterTabs, type FilterTab } from "../components/FilterTabs";
import { PositionCard } from "../components/PositionCard";
import { TopBar } from "../components/TopBar";
import {
  makeApi,
  type ChartPoint,
  type ClosePositionResult,
  type OrderItem,
  type PortfolioSummary,
  type PositionItem,
} from "../lib/api";
import { useAuth } from "../lib/auth";
import { useSSE } from "../lib/sse";

type Tab = "all" | "open" | "closed" | "orders";
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
  const [open, setOpen] = useState<PositionItem[]>([]);
  const [closed, setClosed] = useState<PositionItem[]>([]);
  const [orders, setOrders] = useState<OrderItem[]>([]);
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [chartData, setChartData] = useState<ChartPoint[]>([]);
  const [chartPeriod, setChartPeriod] = useState<Period>("7D");
  const [tab, setTab] = useState<Tab>("open");
  const [error, setError] = useState<string | null>(null);

  // Cash Out modal state
  const [cashOutTarget, setCashOutTarget] = useState<PositionItem | null>(null);
  const [cashOutLoading, setCashOutLoading] = useState(false);
  const [cashOutError, setCashOutError] = useState<string | null>(null);

  const loadPositions = useCallback(async () => {
    try {
      const [o, c, summ] = await Promise.all([
        api.getPositions("open"),
        api.getPositions("closed"),
        api.getPortfolioSummary(),
      ]);
      setOpen(o);
      setClosed(c);
      setSummary(summ);
    } catch (e) {
      setError(String(e));
    }
  }, [api]);

  const loadOrders = useCallback(async () => {
    try {
      const ords = await api.getOrders(50);
      setOrders(ords);
    } catch {
      // non-critical — orders list stays stale
    }
  }, [api]);

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
    portfolio_update: refresh,
  });

  const handleCashOutConfirm = useCallback(async () => {
    if (!cashOutTarget) return;
    setCashOutLoading(true);
    setCashOutError(null);
    try {
      await api.closePosition(cashOutTarget.id);
      setCashOutTarget(null);
      void loadPositions();
    } catch (e) {
      setCashOutError(String(e));
    } finally {
      setCashOutLoading(false);
    }
  }, [api, cashOutTarget, loadPositions]);

  const allPositions = useMemo(() => {
    const combined = [...open, ...closed];
    combined.sort(
      (a, b) =>
        new Date(b.opened_at).getTime() - new Date(a.opened_at).getTime(),
    );
    return combined;
  }, [open, closed]);

  const tabs: FilterTab<Tab>[] = [
    { key: "open", label: "Open", count: open.length },
    { key: "closed", label: "Closed", count: closed.length },
    { key: "all", label: "All", count: open.length + closed.length },
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

        <PnlChart
          data={chartData}
          period={chartPeriod}
          onPeriodChange={(p) => setChartPeriod(p)}
        />

        {error && <div className="text-red text-sm mb-3">{error}</div>}

        <FilterTabs tabs={tabs} active={tab} onChange={setTab} />

        {tab === "open" &&
          (open.length === 0 ? (
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
                />
              ))}
            </div>
          ))}

        {tab === "closed" &&
          (closed.length === 0 ? (
            <EmptyState
              icon="📦"
              title="No Closed Trades"
              text="Closed trades, expiries, and force-exits land here."
            />
          ) : (
            <div className="md:grid md:grid-cols-2 md:gap-3">
              {closed.map((p) => <PositionRow key={p.id} p={p} />)}
            </div>
          ))}

        {tab === "all" &&
          (allPositions.length === 0 ? (
            <EmptyState
              icon="📭"
              title="No Positions"
              text="Your trades will appear here once auto-trade opens a position."
            />
          ) : (
            <div className="md:grid md:grid-cols-2 md:gap-3">
              {allPositions.map((p) => <PositionRow key={p.id} p={p} />)}
            </div>
          ))}

        {tab === "orders" && (
          orders.length === 0 ? (
            <EmptyState
              icon="🧾"
              title="No Orders"
              text="Limit orders from auto-trading will appear here."
            />
          ) : (
            <div className="space-y-2">
              {orders.map((o) => <OrderRow key={o.id} o={o} />)}
            </div>
          )
        )}
      </div>

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
              {cashOutTarget.current_price != null && (
                <> Est. fill ≈ ${(cashOutTarget.size_usdc * cashOutTarget.current_price / Math.max(cashOutTarget.entry_price, 0.0001)).toFixed(2)}</>
              )}
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

// ── Portfolio Header ────────────────────────────────────────────────────────

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

// ── P&L Chart ───────────────────────────────────────────────────────────────

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

// ── Position Row ────────────────────────────────────────────────────────────

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

function PositionRow({ p, onCashOut }: { p: PositionItem; onCashOut?: () => void }) {
  const isOpen = p.status === "open";
  const priceUnavailable = isOpen && p.current_price === null;

  const curVal = (() => {
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

  const metaItems = [
    <span key="cost" className="text-ink-3">
      ${p.size_usdc.toFixed(2)}
    </span>,
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

  return (
    <PositionCard
      market={p.market_question ?? `${p.market_id.slice(0, 18)}…`}
      positionValue={{ value: priceUnavailable ? "—" : `$${curVal.toFixed(2)}`, tone }}
      side={side}
      borderTone={tone}
      meta={metaItems}
      metaAdvanced={[
        <span key="entry">
          {p.side.toUpperCase()} @ {(p.entry_price * 100).toFixed(1)}¢
        </span>,
      ]}
      footer={
        isOpen && onCashOut ? (
          <button
            type="button"
            onClick={onCashOut}
            className="w-full mt-2 clip-btn font-hud text-[9px] font-bold tracking-[1.5px] uppercase py-2 transition-colors"
            style={{
              background: "rgba(255,45,85,0.08)",
              border: "1px solid rgba(255,45,85,0.25)",
              color: "#FF2D55",
            }}
          >
            Cash Out
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

// ── Helpers ─────────────────────────────────────────────────────────────────

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
