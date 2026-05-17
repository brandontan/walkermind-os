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
import { EmptyState } from "../components/EmptyState";
import { FilterTabs, type FilterTab } from "../components/FilterTabs";
import { PositionCard } from "../components/PositionCard";
import { TopBar } from "../components/TopBar";
import {
  makeApi,
  type ChartPoint,
  type PortfolioSummary,
  type PositionItem,
} from "../lib/api";
import { useAuth } from "../lib/auth";
import { useSSE } from "../lib/sse";

type Tab = "all" | "open" | "closed" | "orders";
type Period = "1D" | "1W" | "1M" | "1Y" | "ALL";

const PERIODS: Period[] = ["1D", "1W", "1M", "1Y", "ALL"];

export function PortfolioPage() {
  const { user } = useAuth();
  const api = useMemo(() => makeApi(user?.token ?? null), [user?.token]);
  const [open, setOpen] = useState<PositionItem[]>([]);
  const [closed, setClosed] = useState<PositionItem[]>([]);
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [chartData, setChartData] = useState<ChartPoint[]>([]);
  const [chartPeriod, setChartPeriod] = useState<Period>("1W");
  const [tab, setTab] = useState<Tab>("open");
  const [error, setError] = useState<string | null>(null);

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

  const loadChart = useCallback(
    async (period: Period) => {
      try {
        const data = await api.getPortfolioChart(period);
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

  const refresh = useCallback(() => {
    void loadPositions();
    void loadChart(chartPeriod);
  }, [loadPositions, loadChart, chartPeriod]);

  useSSE(user?.token ?? null, {
    positions: refresh,
    position_opened: refresh,
    position_closed: refresh,
    portfolio_update: refresh,
  });

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
    { key: "orders", label: "Orders", advanced: true },
  ];

  return (
    <>
      <TopBar />
      <div className="px-3.5 pt-3.5 pb-6 animate-page-in">
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
              {open.map((p) => <PositionRow key={p.id} p={p} />)}
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
          <EmptyState
            icon="🧾"
            title="Order Book"
            text="Pending limit orders will show here. (Advanced mode)"
          />
        )}
      </div>
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

type ChartEntry = { label: string; equity: number };

function PnlChart({
  data,
  period,
  onPeriodChange,
}: {
  data: ChartPoint[];
  period: Period;
  onPeriodChange: (p: Period) => void;
}) {
  const chartEntries: ChartEntry[] = data.map((d) => ({
    label: fmtChartTime(d.ts, period),
    equity: d.equity,
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
                strokeDasharray="2 4"
                stroke="rgba(69,83,112,0.25)"
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
              <Tooltip
                contentStyle={{
                  background: "#0A1628",
                  border: "1px solid #1E2D4A",
                  borderRadius: "3px",
                  fontSize: "11px",
                  fontFamily: "monospace",
                  color: "#F0F5FF",
                  padding: "6px 10px",
                }}
                labelStyle={{ color: "#455370", marginBottom: "2px" }}
                formatter={(value: number) => [
                  `$${value.toFixed(2)}`,
                  "Equity",
                ]}
              />
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

function PositionRow({ p }: { p: PositionItem }) {
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
    />
  );
}

// ── Helpers ─────────────────────────────────────────────────────────────────

function fmtChartTime(ts: string, period: Period): string {
  try {
    const d = new Date(ts);
    if (period === "1D")
      return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    if (period === "1W" || period === "1M")
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
