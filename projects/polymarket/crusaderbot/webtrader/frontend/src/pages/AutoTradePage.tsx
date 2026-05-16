import { useCallback, useEffect, useState } from "react";
import { CustomizeDrawer } from "../components/CustomizeDrawer";
import { StrategyCard } from "../components/StrategyCard";
import { makeApi, type AutoTradeState, type CustomizeParams } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useSSE } from "../lib/sse";

const PRESETS = [
  {
    preset_key: "safe_conservative",
    name: "Safe Conservative",
    description: "Low risk, steady accumulation. Best for capital preservation.",
    risk: "safe" as const,
    tp_pct: 10,
    sl_pct: 5,
    capital_pct: 20,
  },
  {
    preset_key: "balanced_growth",
    name: "Balanced Growth",
    description: "Moderate risk with consistent returns.",
    risk: "balanced" as const,
    tp_pct: 20,
    sl_pct: 10,
    capital_pct: 40,
  },
  {
    preset_key: "aggressive_alpha",
    name: "Aggressive Alpha",
    description: "High risk, high reward. Maximum position sizing.",
    risk: "aggressive" as const,
    tp_pct: 35,
    sl_pct: 20,
    capital_pct: 70,
  },
];

export function AutoTradePage() {
  const { user } = useAuth();
  const api = makeApi(user?.token ?? null);
  const [state, setState] = useState<AutoTradeState | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setState(await api.getAutotrade());
  }, [user?.token]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { void load(); }, [load]);

  useSSE(user?.token ?? null, {
    settings: () => void load(),
  });

  async function handleToggle() {
    if (!state) return;
    setLoading(true);
    try {
      await api.toggleAutotrade(!state.auto_trade_on);
      await load();
    } finally {
      setLoading(false);
    }
  }

  async function handleActivate(preset_key: string) {
    await api.activatePreset(preset_key);
    await load();
  }

  async function handleCustomize(params: CustomizeParams) {
    await api.customizeStrategy(params);
    setDrawerOpen(false);
    await load();
  }

  if (!state) return <div className="p-4 text-muted text-sm">Loading…</div>;

  return (
    <div className="pb-24 px-4">
      <div className="flex items-center justify-between pt-6 pb-4">
        <h1 className="text-xl font-bold text-primary">Auto Trade</h1>
      </div>

      {/* Status bar */}
      <div className="bg-card border border-border rounded-xl p-4 mb-4 flex items-center justify-between">
        <div>
          <p className="text-primary font-medium text-sm">
            {state.active_preset?.replace("_", " ") ?? "No preset selected"}
          </p>
          <p className="text-muted text-xs mt-0.5">{state.risk_profile} risk</p>
        </div>
        <button
          onClick={handleToggle}
          disabled={loading}
          className={`px-4 py-1.5 rounded-full text-sm font-semibold transition-colors ${
            state.auto_trade_on
              ? "bg-green/10 text-green border border-green/30 hover:bg-green/20"
              : "bg-muted/10 text-muted border border-border hover:border-amber hover:text-amber"
          }`}
        >
          {state.auto_trade_on ? "Pause" : "Resume"}
        </button>
      </div>

      {/* Strategy cards */}
      <div className="flex flex-col gap-3 mb-4">
        {PRESETS.map((p) => (
          <StrategyCard
            key={p.preset_key}
            {...p}
            isActive={state.active_preset === p.preset_key}
            onActivate={handleActivate}
          />
        ))}
      </div>

      {/* Customize */}
      <button
        onClick={() => setDrawerOpen(true)}
        className="w-full py-3 rounded-xl border border-border text-muted text-sm font-medium hover:border-amber hover:text-amber transition-colors"
      >
        ⚙ Customize Active Strategy
      </button>

      <CustomizeDrawer
        open={drawerOpen}
        initial={{ tp_pct: state.tp_pct, sl_pct: state.sl_pct, capital_alloc_pct: state.capital_alloc_pct }}
        onSave={handleCustomize}
        onClose={() => setDrawerOpen(false)}
      />
    </div>
  );
}
