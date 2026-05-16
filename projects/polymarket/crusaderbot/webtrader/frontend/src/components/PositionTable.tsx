import type { PositionItem } from "../lib/api";

interface PositionTableProps {
  positions: PositionItem[];
}

export function PositionTable({ positions }: PositionTableProps) {
  if (positions.length === 0) {
    return (
      <div className="text-center text-muted py-10 text-sm">No positions found</div>
    );
  }

  return (
    <div className="divide-y divide-border">
      {positions.map((p) => {
        const pnl = p.pnl_usdc ?? 0;
        return (
          <div key={p.id} className="flex items-center justify-between gap-3 py-3">
            <div className="min-w-0 flex-1">
              <p className="text-sm text-primary truncate" title={p.market_question ?? p.market_id}>
                {p.market_question ?? p.market_id.slice(0, 20) + "…"}
              </p>
              <div className="flex items-center gap-1.5 mt-1 flex-wrap">
                <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${p.side === "yes" ? "text-green bg-green/10" : "text-red bg-red/10"}`}>
                  {p.side.toUpperCase()}
                </span>
                <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${p.status === "open" ? "text-blue bg-blue/10" : "text-muted bg-muted/10"}`}>
                  {p.status.toUpperCase()}
                </span>
                <span className="text-xs text-muted font-mono">
                  ${p.size_usdc.toFixed(2)} · {(p.entry_price * 100).toFixed(1)}¢
                  {p.current_price != null ? ` → ${(p.current_price * 100).toFixed(1)}¢` : ""}
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
  );
}
