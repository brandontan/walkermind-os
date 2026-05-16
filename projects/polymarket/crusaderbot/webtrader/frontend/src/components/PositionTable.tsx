import type { PositionItem } from "../lib/api";

interface PositionTableProps {
  positions: PositionItem[];
}

export function PositionTable({ positions }: PositionTableProps) {
  if (positions.length === 0) {
    return (
      <div className="text-center text-muted py-8 text-sm">No positions found</div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-muted text-xs border-b border-border">
            <th className="text-left py-2 pr-3">Market</th>
            <th className="text-left py-2 pr-3">Side</th>
            <th className="text-right py-2 pr-3">Size</th>
            <th className="text-right py-2 pr-3">PnL</th>
            <th className="text-right py-2">Status</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((p) => {
            const pnl = p.pnl_usdc ?? 0;
            const pnlColor = pnl >= 0 ? "text-green" : "text-red";
            return (
              <tr key={p.id} className="border-b border-border/50 hover:bg-card/50">
                <td className="py-2 pr-3 text-primary max-w-[120px] truncate" title={p.market_question ?? p.market_id}>
                  {p.market_question ?? p.market_id.slice(0, 12) + "…"}
                </td>
                <td className="py-2 pr-3">
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                    p.side === "yes" ? "bg-green/10 text-green" : "bg-red/10 text-red"
                  }`}>
                    {p.side === "yes" ? "YES" : "NO"}
                  </span>
                </td>
                <td className="py-2 pr-3 text-right">${p.size_usdc.toFixed(2)}</td>
                <td className={`py-2 pr-3 text-right font-medium ${pnlColor}`}>
                  {pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}
                </td>
                <td className="py-2 text-right">
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                    p.status === "open" ? "bg-green/10 text-green" : "bg-muted/20 text-muted"
                  }`}>
                    {p.status.toUpperCase()}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
