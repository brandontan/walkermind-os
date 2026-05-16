import { useCallback, useEffect, useState } from "react";
import { CustomizeDrawer } from "../components/CustomizeDrawer";
import { StrategyCard } from "../components/StrategyCard";
import { makeApi, type AutoTradeState, type CustomizeParams } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useSSE } from "../lib/sse";

// Preset keys match domain/preset/presets.py — display names adapted to spec
const PRESETS = [
  {
    preset_key:  "signal_sniper",
    emoji:       "🎯",
    name:        "Safe Scout",
    description: "Low frequency signal trading. Best for capital preservation.",
    risk:        "safe" as const,
    tp_pct:      15,
    sl_pct:      8,
    capital_pct: 20,
    freq:        "Low",
  },
  {
    preset_key:  "full_auto",
    emoji:       "⚡",
    name:        "Full Auto",
    description: "All strategies active. Balanced exposure and steady returns.",
    risk:        "balanced" as const,
    tp_pct:      20,
    sl_pct:      15,
    capital_pct: 80,
    freq:        "Med",
  },
  {
    preset_key:  "value_hunter",
    emoji:       "🔥",
    name:        "Aggressive",
    description: "Mispriced market edge model. High reward, requires patience.",
    risk:        "aggressive" as const,
    tp_pct:      25,
    sl_pct:      12,
    capital_pct: 100,
    freq:        "High",
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

  const activePreset = PRESETS.find((p) => p.preset_key === state.active_preset);

  return (
    <div className="pb-28 px-4 animate-page-in">
      <div className="flex items-center justify-between pt-6 pb-4">
        <h1 className="text-xl font-bold text-primary">Auto Trade</h1>
      </div>

      {/* Active strategy status card */}
      <div className="bg-surface border border-border rounded-2xl p-5 mb-5">
        <div className="flex items-center justify-between mb-1">
          <div>
            <p className="text-primary font-semibold text-base">
              {activePreset
                ? `${activePreset.emoji} ${activePreset.name}`
                : (state.active_preset ?? "No preset selected")}
            </p>
            <p className="text-muted text-xs mt-0.5 capitalize">{state.risk_profile} risk</p>
          </div>
          <button
            onClick={handleToggle}
            disabled={loading}
            className={`px-4 py-1.5 rounded-full text-sm font-semibold transition-colors ${
              state.auto_trade_on
                ? "bg-green/10 text-green border border-green/30 hover:bg-green/20"
                : "bg-muted/10 text-muted border border-border hover:border-gold hover:text-gold"
            }`}
          >
            {state.auto_trade_on ? "Pause" : "Resume"}
          </button>
        </div>
        {state.tp_pct > 0 && (
          <div className="flex gap-4 text-xs text-muted mt-3">
            <span>TP <span className="text-green font-medium font-mono">{(state.tp_pct * 100).toFixed(0)}%</span></span>
            <span>SL <span className="text-red font-medium font-mono">{(state.sl_pct * 100).toFixed(0)}%</span></span>
            <span>Cap <span className="text-primary font-medium font-mono">{(state.capital_alloc_pct * 100).toFixed(0)}%</span></span>
          </div>
        )}
      </div>

      {/* Strategy selector cards */}
      <div className="flex flex-col gap-3 mb-5">
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
        className="w-full py-3 rounded-xl border border-border text-muted text-sm font-medium hover:border-gold hover:text-gold transition-colors"
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
