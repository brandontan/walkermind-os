import { useCallback, useEffect, useMemo, useState } from "react";
import { AdvancedOnly } from "../components/AdvancedGate";
import { HeroCard } from "../components/HeroCard";
import { SettingsGroup, SettingsRow } from "../components/SettingsGroup";
import { StrategyCard } from "../components/StrategyCard";
import { TopBar } from "../components/TopBar";
import { makeApi, type AutoTradeState } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useSSE } from "../lib/sse";

// Preset keys mirror domain/preset/presets.py.
// Display surface follows the v3.2 mock (Conservative / Balanced / Aggressive).
const PRESETS = [
  {
    preset_key:  "signal_sniper",
    name:        "Conservative",
    description: "Low risk. Capped at 20% capital per position. Slow but steady.",
    risk:        "safe" as const,
    capital_pct: 20,
    tp_pct:      10,
    sl_pct:      5,
  },
  {
    preset_key:  "full_auto",
    name:        "Balanced",
    description: "Medium risk. Up to 40% capital. Balanced TP/SL for steady growth.",
    risk:        "balanced" as const,
    capital_pct: 40,
    tp_pct:      20,
    sl_pct:      15,
  },
  {
    preset_key:  "value_hunter",
    name:        "Aggressive",
    description: "High risk. Up to 60% capital. Targets bigger wins, accepts deeper drawdowns.",
    risk:        "aggressive" as const,
    capital_pct: 60,
    tp_pct:      30,
    sl_pct:      20,
  },
];

export function AutoTradePage() {
  const { user } = useAuth();
  const api = useMemo(() => makeApi(user?.token ?? null), [user?.token]);
  const [state, setState] = useState<AutoTradeState | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setState(await api.getAutotrade());
  }, [api]);

  useEffect(() => { void load(); }, [load]);
  useSSE(user?.token ?? null, { settings: () => void load() });

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

  if (!state) return (
    <>
      <TopBar />
      <div className="p-4 text-ink-3 text-sm font-mono">Loading…</div>
    </>
  );

  const active = PRESETS.find((p) => p.preset_key === state.active_preset);
  const heroValue = active ? active.name.toUpperCase() : "IDLE";

  return (
    <>
      <TopBar />
      <div className="px-3.5 pt-3.5 pb-6 animate-page-in">

        <HeroCard
          label="Auto Trade"
          value={heroValue}
          valueFontSize={42}
          prefix=""
          statusLabel={state.auto_trade_on ? "STRATEGY ACTIVE" : "STRATEGY PAUSED"}
          metaItems={
            <>
              <span className={state.auto_trade_on ? "text-grn font-bold" : "text-ink-2 font-bold"}>
                {state.auto_trade_on ? "● RUNNING" : "● PAUSED"}
              </span>
              <span className="text-ink-4">│</span>
              <span>{active ? active.risk.toUpperCase() : "—"}</span>
            </>
          }
          {...(state.auto_trade_on
            ? { ctaDanger: { label: "🛑 Stop Auto Trade", onClick: () => void handleToggle() } }
            : {
                ctaPrimary:   { label: loading ? "Starting…" : "▶ Start Auto Trade", onClick: () => void handleToggle() },
                ctaSecondary: { label: "Edit Risk", onClick: () => { /* future drawer */ } },
              })}
        />

        <SectionTitle>Select Strategy</SectionTitle>
        {PRESETS.map((p) => (
          <StrategyCard
            key={p.preset_key}
            preset_key={p.preset_key}
            name={p.name}
            description={p.description}
            risk={p.risk}
            tp_pct={p.tp_pct}
            sl_pct={p.sl_pct}
            capital_pct={p.capital_pct}
            isActive={state.active_preset === p.preset_key}
            onActivate={handleActivate}
          />
        ))}

        <AdvancedOnly>
          <SectionTitle>Configuration</SectionTitle>
          <SettingsGroup title="Active Parameters">
            <SettingsRow
              name="Capital Allocation"
              desc="Max % of balance per trade"
              control={`${Math.round(state.capital_alloc_pct * 100)}%`}
            />
            <SettingsRow
              name="Take Profit"
              desc="Auto-close when price moves +%"
              control={`+${Math.round(state.tp_pct * 100)}%`}
            />
            <SettingsRow
              name="Stop Loss"
              desc="Auto-close when price drops −%"
              control={`−${Math.round(state.sl_pct * 100)}%`}
            />
            <SettingsRow
              name="Risk Profile"
              desc="Current preset risk tier"
              control={state.risk_profile.toUpperCase()}
            />
          </SettingsGroup>
        </AdvancedOnly>
      </div>
    </>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between mt-3.5 mb-2 mx-0.5">
      <div className="font-hud text-[10px] font-bold tracking-[3px] text-ink-2 uppercase flex items-center gap-2">
        <span className="w-3 h-px bg-gold" aria-hidden />
        {children}
      </div>
    </div>
  );
}
