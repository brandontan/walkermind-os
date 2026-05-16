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
import { makeApi, type PositionItem } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useSSE } from "../lib/sse";

type Filter    = "all" | "open" | "closed";
type ChartRange = "7D" | "30D" | "ALL";

function buildChartData(positions: PositionItem[], range: ChartRange) {
  const closed = positions.filter((p) => p.status === "closed" && p.pnl_usdc != null);
  if (closed.length === 0) return [];

  const now  = Date.now();
  const msIn = { "7D": 7 * 86400e3, "30D": 30 * 86400e3, ALL: Infinity };
  const cutoff = range === "ALL" ? 0 : now - msIn[range];

  const closeTime = (p: PositionItem) =>
    new Date(p.closed_at ?? p.opened_at).getTime();

  const filtered = closed
    .filter((p) => closeTime(p) >= cutoff)
    .sort((a, b) => closeTime(a) - closeTime(b));

  if (filtered.length === 0) return [];

  let cumulative = 0;
  return filtered.map((p) => {
    cumulative += p.pnl_usdc ?? 0;
    const d = new Date(p.closed_at ?? p.opened_at);
    return {
      label: d.toLocaleDateString([], { month: "short", day: "numeric" }),
      pnl:   parseFloat(cumulative.toFixed(2)),
    };
  });
}

export function PortfolioPage() {
  const { user } = useAuth();
  const api = makeApi(user?.token ?? null);
  const [positions, setPositions]   = useState<PositionItem[]>([]);
  const [filter, setFilter]         = useState<Filter>("all");
  const [chartRange, setChartRange] = useState<ChartRange>("7D");

  const loadAll = useCallback(async () => {
    setPositions(await api.getPositions());
  }, [user?.token]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { void loadAll(); }, [loadAll]);

  useSSE(user?.token ?? null, {
    positions: () => void loadAll(),
    fills:     () => void loadAll(),
  });

  const displayed = useMemo(() => {
    if (filter === "all") return positions;
    return positions.filter((p) => p.status === filter);
  }, [positions, filter]);

  const chartData = useMemo(() => buildChartData(positions, chartRange), [positions, chartRange]);
  const hasChartData = chartData.length > 0;

  const FILTERS: { key: Filter; label: string }[] = [
    { key: "all",    label: "All"    },
    { key: "open",   label: "Open"   },
    { key: "closed", label: "Closed" },
  ];
  const RANGES: ChartRange[] = ["7D", "30D", "ALL"];

  return (
    <div className="pb-28 px-4 animate-page-in">
      <div className="pt-6 pb-4">
        <h1 className="text-xl font-bold text-primary">Portfolio</h1>
      </div>

      {/* PnL chart */}
      <div className="bg-card border border-border rounded-2xl p-4 mb-4">
        <div className="flex items-center justify-between mb-3">
          <p className="text-sm font-semibold text-primary">PnL Overview</p>
          <div className="flex gap-1">
            {RANGES.map((r) => (
              <button
                key={r}
                onClick={() => setChartRange(r)}
                className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-colors ${
                  chartRange === r
                    ? "bg-gold/15 text-gold border border-gold/30"
                    : "text-muted hover:text-primary"
                }`}
              >
                {r}
              </button>
            ))}
          </div>
        </div>

        {hasChartData ? (
          <ResponsiveContainer width="100%" height={160}>
            <AreaChart data={chartData} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
              <defs>
                <linearGradient id="pnlGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor="#00D68F" stopOpacity={0.25} />
                  <stop offset="95%" stopColor="#00D68F" stopOpacity={0}    />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="rgba(255,255,255,0.04)" strokeDasharray="4 4" vertical={false} />
              <XAxis
                dataKey="label"
                tick={{ fill: "#6B7280", fontSize: 10 }}
                axisLine={false}
                tickLine={false}
                interval="preserveStartEnd"
              />
              <YAxis
                tick={{ fill: "#6B7280", fontSize: 10 }}
                axisLine={false}
                tickLine={false}
                tickFormatter={(v: number) => `$${v}`}
              />
              <Tooltip
                contentStyle={{ background: "#131920", border: "1px solid #1A2332", borderRadius: 8, fontSize: 12 }}
                labelStyle={{ color: "#F0F0F5" }}
                itemStyle={{ color: "#00D68F" }}
                formatter={(v: number) => [`$${v.toFixed(2)}`, "Cum. PnL"]}
              />
              <Area
                type="monotone"
                dataKey="pnl"
                stroke="#00D68F"
                strokeWidth={2}
                fill="url(#pnlGradient)"
                dot={false}
                activeDot={{ r: 4, fill: "#00D68F" }}
              />
            </AreaChart>
          </ResponsiveContainer>
        ) : (
          <div className="flex flex-col items-center justify-center h-[160px] gap-2">
            <p className="text-muted text-sm">No closed trades yet</p>
            <p className="text-muted/60 text-xs">Chart updates on first close</p>
          </div>
        )}
      </div>

      {/* Filter tabs */}
      <div className="flex gap-2 mb-4">
        {FILTERS.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setFilter(key)}
            className={`px-4 py-1.5 rounded-full text-sm font-medium transition-colors ${
              filter === key
                ? "bg-gold text-bg"
                : "bg-card border border-border text-muted hover:border-gold hover:text-gold"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Position list */}
      <div className="bg-card border border-border rounded-2xl overflow-hidden">
        {displayed.length === 0 ? (
          <div className="text-center text-muted py-10 text-sm">No positions found</div>
        ) : (
          <div className="divide-y divide-border">
            {displayed.map((p) => {
              const pnl = p.pnl_usdc ?? 0;
              return (
                <div key={p.id} className="flex items-center justify-between gap-3 px-4 py-3">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm text-primary truncate">
                      {p.market_question ?? p.market_id.slice(0, 20) + "…"}
                    </p>
                    <div className="flex items-center gap-1.5 mt-1 flex-wrap">
                      <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${p.side === "yes" ? "text-green bg-green/10" : "text-red bg-red/10"}`}>
                        {p.side.toUpperCase()}
                      </span>
                      <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${p.status === "open" ? "text-blue bg-blue/10" : "text-muted bg-muted/10"}`}>
                        {p.status.toUpperCase()}
                      </span>
                      <span className="text-xs px-1.5 py-0.5 rounded font-medium text-gold bg-gold/10">
                        {p.mode.toUpperCase()}
                      </span>
                      <span className="text-xs text-muted font-mono">
                        ${p.size_usdc.toFixed(2)} · {(p.entry_price * 100).toFixed(1)}¢ → {p.current_price != null ? `${(p.current_price * 100).toFixed(1)}¢` : "—"}
                      </span>
                    </div>
                  </div>
                  <p className={`text-sm font-semibold font-mono shrink-0 ${pnl >= 0 ? "text-green" : "text-red"}`}>
                    {pnl >= 0 ? "+" : ""}${Math.abs(pnl).toFixed(2)}
                  </p>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
