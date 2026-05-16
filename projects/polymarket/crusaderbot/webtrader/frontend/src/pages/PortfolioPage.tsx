import { useCallback, useEffect, useState } from "react";
import { PositionTable } from "../components/PositionTable";
import { makeApi, type PositionItem } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useSSE } from "../lib/sse";

type Filter = "all" | "open" | "closed";

export function PortfolioPage() {
  const { user } = useAuth();
  const api = makeApi(user?.token ?? null);
  const [positions, setPositions] = useState<PositionItem[]>([]);
  const [filter, setFilter] = useState<Filter>("all");

  const load = useCallback(async () => {
    const status = filter === "all" ? undefined : filter;
    setPositions(await api.getPositions(status));
  }, [filter, user?.token]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { void load(); }, [load]);

  useSSE(user?.token ?? null, {
    positions: () => void load(),
    fills:     () => void load(),
  });

  const FILTERS: { key: Filter; label: string }[] = [
    { key: "all",    label: "All" },
    { key: "open",   label: "Open" },
    { key: "closed", label: "Closed" },
  ];

  return (
    <div className="pb-24 px-4">
      <div className="pt-6 pb-4">
        <h1 className="text-xl font-bold text-primary">Portfolio</h1>
      </div>

      {/* Filter tabs */}
      <div className="flex gap-2 mb-4">
        {FILTERS.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setFilter(key)}
            className={`px-4 py-1.5 rounded-full text-sm font-medium transition-colors ${
              filter === key
                ? "bg-amber text-bg"
                : "bg-card border border-border text-muted hover:border-amber hover:text-amber"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="bg-card border border-border rounded-xl p-4">
        <PositionTable positions={positions} />
      </div>
    </div>
  );
}
