import { useState } from "react";
import type { CustomizeParams } from "../lib/api";

interface CustomizeDrawerProps {
  open: boolean;
  initial: CustomizeParams;
  onSave: (params: CustomizeParams) => void;
  onClose: () => void;
}

const MARKET_FILTERS = ["All", "Politics", "Sports", "Finance", "Crypto"] as const;

export function CustomizeDrawer({ open, initial, onSave, onClose }: CustomizeDrawerProps) {
  const [tp, setTp] = useState(initial.tp_pct ?? 20);
  const [sl, setSl] = useState(initial.sl_pct ?? 10);
  const [capital, setCapital] = useState((initial.capital_alloc_pct ?? 0.5) * 100);
  const [maxTrades, setMaxTrades] = useState(initial.max_position_pct ?? 5);
  const [autoRedeem, setAutoRedeem] = useState(initial.auto_redeem_mode !== "off");
  const [marketFilter, setMarketFilter] = useState(
    initial.category_filters?.[0] ?? "All"
  );

  if (!open) return null;

  function handleSave() {
    onSave({
      tp_pct: tp / 100,
      sl_pct: sl / 100,
      capital_alloc_pct: capital / 100,
      max_position_pct: maxTrades / 100,
      auto_redeem_mode: autoRedeem ? "hourly" : "off",
      category_filters: marketFilter === "All" ? [] : [marketFilter.toLowerCase()],
    });
  }

  return (
    <>
      <div className="fixed inset-0 bg-black/60 z-40" onClick={onClose} />
      <div className="fixed bottom-0 left-1/2 -translate-x-1/2 w-full max-w-mobile bg-card border-t border-border rounded-t-2xl z-50 p-6 pb-8">
        <h3 className="text-primary font-semibold text-lg mb-5">Customize Strategy</h3>

        <NumericField label="Take Profit %" value={tp} min={1} max={100} onChange={setTp} />
        <NumericField label="Stop Loss %" value={sl} min={1} max={50} onChange={setSl} />
        <NumericField label="Capital %" value={capital} min={5} max={100} onChange={setCapital} />
        <NumericField label="Max Open Trades" value={maxTrades} min={1} max={10} onChange={setMaxTrades} />

        <div className="flex items-center justify-between mb-4">
          <span className="text-primary text-sm">Auto-Redeem</span>
          <button
            onClick={() => setAutoRedeem(!autoRedeem)}
            className={`w-12 h-6 rounded-full transition-colors ${autoRedeem ? "bg-amber" : "bg-border"}`}
          >
            <span className={`block w-5 h-5 rounded-full bg-white transition-transform mx-0.5 ${autoRedeem ? "translate-x-6" : "translate-x-0"}`} />
          </button>
        </div>

        <div className="mb-6">
          <label className="text-muted text-xs mb-1 block">Market Filter</label>
          <select
            value={marketFilter}
            onChange={(e) => setMarketFilter(e.target.value)}
            className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-primary text-sm"
          >
            {MARKET_FILTERS.map((f) => (
              <option key={f} value={f}>{f}</option>
            ))}
          </select>
        </div>

        <div className="flex gap-3">
          <button onClick={onClose} className="flex-1 py-3 rounded-xl border border-border text-muted text-sm font-medium">
            Cancel
          </button>
          <button
            onClick={handleSave}
            className="flex-1 py-3 rounded-xl bg-amber text-bg text-sm font-semibold hover:bg-amber/90 transition-colors"
          >
            Save & Apply
          </button>
        </div>
      </div>
    </>
  );
}

interface NumericFieldProps {
  label: string;
  value: number;
  min: number;
  max: number;
  onChange: (v: number) => void;
}

function NumericField({ label, value, min, max, onChange }: NumericFieldProps) {
  return (
    <div className="flex items-center justify-between mb-4">
      <span className="text-primary text-sm">{label}</span>
      <div className="flex items-center gap-2">
        <button
          onClick={() => onChange(Math.max(min, value - 1))}
          className="w-7 h-7 rounded-full border border-border text-muted flex items-center justify-center hover:border-amber hover:text-amber transition-colors"
        >−</button>
        <span className="text-primary font-medium w-10 text-center">{value}</span>
        <button
          onClick={() => onChange(Math.min(max, value + 1))}
          className="w-7 h-7 rounded-full border border-border text-muted flex items-center justify-center hover:border-amber hover:text-amber transition-colors"
        >+</button>
      </div>
    </div>
  );
}
