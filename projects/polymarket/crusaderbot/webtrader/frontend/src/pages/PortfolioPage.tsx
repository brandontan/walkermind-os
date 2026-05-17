import { useCallback, useEffect, useMemo, useState } from "react";
import { EmptyState } from "../components/EmptyState";
import { FilterTabs, type FilterTab } from "../components/FilterTabs";
import { PositionCard } from "../components/PositionCard";
import { TopBar } from "../components/TopBar";
import { makeApi, type PositionItem } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useSSE } from "../lib/sse";

type Tab = "open" | "closed" | "orders";

export function PortfolioPage() {
  const { user } = useAuth();
  const api = useMemo(() => makeApi(user?.token ?? null), [user?.token]);
  const [open, setOpen] = useState<PositionItem[]>([]);
  const [closed, setClosed] = useState<PositionItem[]>([]);
  const [tab, setTab] = useState<Tab>("open");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [o, c] = await Promise.all([
        api.getPositions("open"),
        api.getPositions("closed"),
      ]);
      setOpen(o);
      setClosed(c);
    } catch (e) {
      setError(String(e));
    }
  }, [api]);

  useEffect(() => { void load(); }, [load]);
  useSSE(user?.token ?? null, { positions: () => void load() });

  const tabs: FilterTab<Tab>[] = [
    { key: "open",   label: "Open",   count: open.length },
    { key: "closed", label: "Closed", count: closed.length },
    { key: "orders", label: "Orders", advanced: true },
  ];

  return (
    <>
      <TopBar />
      <div className="px-3.5 pt-3.5 pb-6 animate-page-in">
        <FilterTabs tabs={tabs} active={tab} onChange={setTab} />

        {error && <div className="text-red text-sm mb-3">{error}</div>}

        {tab === "open" && (
          open.length === 0 ? (
            <EmptyState
              icon="📭"
              title="No Open Positions"
              text="When auto-trade opens a position, it will appear here in real-time."
            />
          ) : (
            open.map((p) => <PositionRow key={p.id} p={p} />)
          )
        )}

        {tab === "closed" && (
          closed.length === 0 ? (
            <EmptyState
              icon="📦"
              title="No Closed Trades"
              text="Closed trades, expiries, and force-exits land here."
            />
          ) : (
            closed.map((p) => <PositionRow key={p.id} p={p} />)
          )
        )}

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

function PositionRow({ p }: { p: PositionItem }) {
  // Show current market value of the position, not raw PnL.
  // Open: (current_price ?? entry_price) / entry_price * size_usdc
  // Closed/expired: cost + realized pnl_usdc (what was actually returned)
  const curVal = (() => {
    if (p.status === "open") {
      const price = p.current_price ?? p.entry_price;
      return p.entry_price > 0 ? (price / p.entry_price) * p.size_usdc : p.size_usdc;
    }
    return p.size_usdc + (p.pnl_usdc ?? 0);
  })();
  const diff = curVal - p.size_usdc;
  const tone: "zero" | "up" | "dn" =
    Math.abs(diff) < 0.005 ? "zero" : diff > 0 ? "up" : "dn";
  const positionValue = { value: `$${curVal.toFixed(2)}`, tone };
  const side =
    p.status === "expired" ? "exp" : p.side === "no" ? "no" : "yes";

  return (
    <PositionCard
      market={p.market_question ?? `${p.market_id.slice(0, 18)}…`}
      positionValue={positionValue}
      side={side}
      meta={[
        <>${p.size_usdc.toFixed(2)}</>,
        <>{formatTime(p.closed_at ?? p.opened_at)}</>,
      ]}
      metaAdvanced={[
        <>{p.side.toUpperCase()} @ {(p.entry_price * 100).toFixed(1)}¢</>,
      ]}
    />
  );
}

function formatTime(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return ts.slice(11, 16);
  }
}
