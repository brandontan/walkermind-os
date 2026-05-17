import { useCallback, useEffect, useMemo, useState } from "react";
import { HeroCard } from "../components/HeroCard";
import { TopBar } from "../components/TopBar";
import { makeApi, type AutoTradeState, type RiskProfileParams } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useSSE } from "../lib/sse";

// ── Section A: Strategy Presets (mapped to lib/strategies/ classes) ───────────

const STRATEGY_PRESETS = [
  {
    key: "whale_mirror",
    name: "Whale Mirror",
    emoji: "🐋",
    engine: "WhaleTrackingStrategy",
    signal: "High volume + unusual whale activity",
    risk: "safe" as const,
    freq: "Low",
  },
  {
    key: "trend_breakout",
    name: "Trend Breakout",
    emoji: "📈",
    engine: "TrendBreakoutStrategy",
    signal: "Price rise ≥8% in 24h + volume spike",
    risk: "balanced" as const,
    freq: "Medium",
  },
  {
    key: "contrarian",
    name: "Contrarian",
    emoji: "🔄",
    engine: "MomentumStrategy",
    signal: "Price drop ≥10% in 24h + liquidity OK",
    risk: "balanced" as const,
    freq: "Medium",
  },
  {
    key: "value_hunter",
    name: "Value Hunter",
    emoji: "🎯",
    engine: "ValueInvestorStrategy",
    signal: "Fair value gap ≥15% vs market price",
    risk: "advanced" as const,
    freq: "Low",
  },
  {
    key: "close_sweep",
    name: "Close Sweep",
    emoji: "⏰",
    engine: "ExpirationTimingStrategy",
    signal: "Near-expiry + momentum direction",
    risk: "advanced" as const,
    freq: "Low",
  },
  {
    key: "pair_arb",
    name: "Pair Arb",
    emoji: "💰",
    engine: "PairArbStrategy",
    signal: "YES + NO price < $0.95 (guaranteed spread)",
    risk: "safe" as const,
    freq: "Medium",
  },
  {
    key: "ensemble",
    name: "Ensemble",
    emoji: "🤖",
    engine: "EnsembleStrategy",
    signal: "3/5 strategy consensus voting",
    risk: "advanced" as const,
    freq: "High",
  },
  {
    key: "full_auto",
    name: "Full Auto",
    emoji: "🚀",
    engine: "All strategies",
    signal: "Maximum signal coverage",
    risk: "aggressive" as const,
    freq: "High",
  },
] as const;

const COMING_SOON = [
  { name: "Logic Arb",     emoji: "🧠", note: "Needs LLM API" },
  { name: "Sentiment",     emoji: "📰", note: "Needs social API" },
  { name: "Weather Arb",   emoji: "🌦️", note: "Needs NOAA API" },
  { name: "Market Making", emoji: "🏦", note: "Needs WebSocket" },
];

// ── Section B: Risk Profiles ──────────────────────────────────────────────────

const RISK_PROFILES = [
  { key: "conservative" as const, name: "Conservative", emoji: "🟢", capital: 20, tp: 10,  sl: 5  },
  { key: "balanced"     as const, name: "Balanced",     emoji: "🟡", capital: 40, tp: 20,  sl: 15 },
  { key: "aggressive"   as const, name: "Aggressive",   emoji: "🔴", capital: 60, tp: 30,  sl: 20 },
  { key: "custom"       as const, name: "Custom Risk",  emoji: "⚙️", capital: null, tp: null, sl: null },
];

const riskColor: Record<string, string> = {
  safe:       "text-grn",
  balanced:   "text-amber-400",
  advanced:   "text-amber-500",
  aggressive: "text-red-400",
};

// ── Component ─────────────────────────────────────────────────────────────────

export function AutoTradePage() {
  const { user } = useAuth();
  const api = useMemo(() => makeApi(user?.token ?? null), [user?.token]);
  const [state, setState] = useState<AutoTradeState | null>(null);
  const [loading, setLoading] = useState(false);

  // Custom risk inputs
  const [customCapital, setCustomCapital] = useState("20");
  const [customTp, setCustomTp]           = useState("15");
  const [customSl, setCustomSl]           = useState("10");
  const [customErr, setCustomErr]         = useState<string | null>(null);
  const [savingRisk, setSavingRisk]       = useState(false);

  const load = useCallback(async () => {
    const s = await api.getAutotrade();
    setState(s);
    if (s.risk_profile === "custom") {
      setCustomCapital(String(Math.round(s.capital_alloc_pct * 100)));
      setCustomTp(String(Math.round(s.tp_pct * 100)));
      setCustomSl(String(Math.round(s.sl_pct * 100)));
    }
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

  async function handleActivatePreset(key: string) {
    await api.activatePreset(key);
    await load();
  }

  async function handleActivateRisk(profile: RiskProfileParams["profile"]) {
    if (profile === "custom") return; // custom handled by save button
    await api.setRiskProfile({ profile });
    await load();
  }

  async function handleSaveCustomRisk() {
    setCustomErr(null);
    const cap = parseFloat(customCapital) / 100;
    const tp  = parseFloat(customTp) / 100;
    const sl  = parseFloat(customSl) / 100;
    if (isNaN(cap) || isNaN(tp) || isNaN(sl)) {
      setCustomErr("Enter valid numbers for all fields.");
      return;
    }
    if (cap > 0.80) {
      setCustomErr("Capital may not exceed 80%.");
      return;
    }
    if (tp <= sl) {
      setCustomErr("Take Profit must be greater than Stop Loss.");
      return;
    }
    setSavingRisk(true);
    try {
      await api.setRiskProfile({ profile: "custom", capital_alloc_pct: cap, tp_pct: tp, sl_pct: sl });
      await load();
    } catch (e: unknown) {
      setCustomErr(e instanceof Error ? e.message : "Save failed.");
    } finally {
      setSavingRisk(false);
    }
  }

  if (!state) return (
    <>
      <TopBar />
      <div className="p-4 text-ink-3 text-sm font-mono">Loading…</div>
    </>
  );

  const activeStrategy = STRATEGY_PRESETS.find(p => p.key === state.active_preset);
  const heroValue = activeStrategy ? activeStrategy.name.toUpperCase() : "IDLE";

  return (
    <>
      <TopBar />
      <div className="px-3.5 pt-3.5 pb-6 animate-page-in">

        {/* Hero */}
        <HeroCard
          label="Auto Trade"
          value={heroValue}
          valueFontSize={38}
          prefix=""
          statusLabel={state.auto_trade_on ? "STRATEGY ACTIVE" : "STRATEGY PAUSED"}
          metaItems={
            <>
              <span className={state.auto_trade_on ? "text-grn font-bold" : "text-ink-2 font-bold"}>
                {state.auto_trade_on ? "● RUNNING" : "● PAUSED"}
              </span>
              <span className="text-ink-4">│</span>
              <span className="text-ink-3">
                {state.risk_profile.toUpperCase()} RISK
              </span>
            </>
          }
          {...(state.auto_trade_on
            ? { ctaDanger: { label: "🛑 Stop Auto Trade", onClick: () => void handleToggle() } }
            : {
                ctaPrimary: {
                  label: loading ? "Starting…" : "▶ Start Auto Trade",
                  onClick: () => void handleToggle(),
                },
              })}
        />

        {/* ── SECTION A: Strategy Preset ── */}
        <SectionTitle>Strategy Preset</SectionTitle>
        <p className="text-ink-3 text-xs font-mono mb-3 mx-0.5">
          Select the algorithm to drive your trades. Independent of risk sizing.
        </p>

        <div className="grid grid-cols-1 gap-2">
          {STRATEGY_PRESETS.map((p) => {
            const isActive = state.active_preset === p.key;
            return (
              <button
                key={p.key}
                onClick={() => void handleActivatePreset(p.key)}
                className={[
                  "w-full text-left p-3 rounded-lg border transition-all",
                  isActive
                    ? "border-gold bg-surface-2 shadow-[0_0_8px_rgba(191,155,48,0.25)]"
                    : "border-surface-3 bg-surface-1 hover:border-ink-3",
                ].join(" ")}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="text-lg">{p.emoji}</span>
                    <div className="min-w-0">
                      <div className="font-hud text-sm font-bold text-ink-1 flex items-center gap-2">
                        {p.name}
                        {isActive && (
                          <span className="text-[9px] font-bold tracking-widest text-gold uppercase px-1.5 py-0.5 rounded border border-gold/40 bg-gold/10">
                            ACTIVE
                          </span>
                        )}
                      </div>
                      <div className="text-xs text-ink-3 truncate mt-0.5">{p.signal}</div>
                    </div>
                  </div>
                  <div className="text-right shrink-0 text-xs text-ink-3">
                    <div className={`font-bold ${riskColor[p.risk]} uppercase`}>{p.risk}</div>
                    <div className="text-ink-4">{p.freq} freq</div>
                  </div>
                </div>
                <div className="mt-1.5 text-[10px] text-ink-4 font-mono">
                  Engine: {p.engine}
                </div>
              </button>
            );
          })}

          {/* Coming Soon cards */}
          {COMING_SOON.map((cs) => (
            <div
              key={cs.name}
              className="w-full p-3 rounded-lg border border-surface-3 bg-surface-1/50 opacity-50 cursor-not-allowed"
            >
              <div className="flex items-center gap-2">
                <span className="text-lg">{cs.emoji}</span>
                <div>
                  <div className="font-hud text-sm font-bold text-ink-2 flex items-center gap-2">
                    {cs.name}
                    <span className="text-[9px] font-bold tracking-widest text-ink-3 uppercase px-1.5 py-0.5 rounded border border-ink-4/40 bg-surface-2">
                      COMING SOON
                    </span>
                  </div>
                  <div className="text-xs text-ink-4">{cs.note}</div>
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* ── SECTION B: Risk Profile ── */}
        <SectionTitle>Risk Profile</SectionTitle>
        <p className="text-ink-3 text-xs font-mono mb-3 mx-0.5">
          Controls capital %, take profit, and stop loss. Applies to all trade types.
        </p>

        <div className="grid grid-cols-2 gap-2">
          {RISK_PROFILES.map((rp) => {
            const isActive = state.risk_profile === rp.key;
            return (
              <button
                key={rp.key}
                onClick={() => void handleActivateRisk(rp.key)}
                className={[
                  "text-left p-3 rounded-lg border transition-all",
                  isActive
                    ? "border-gold bg-surface-2 shadow-[0_0_8px_rgba(191,155,48,0.2)]"
                    : "border-surface-3 bg-surface-1 hover:border-ink-3",
                  rp.key === "custom" ? "col-span-2" : "",
                ].join(" ")}
              >
                <div className="flex items-center gap-1.5 mb-1">
                  <span>{rp.emoji}</span>
                  <span className="font-hud text-xs font-bold text-ink-1">{rp.name}</span>
                  {isActive && (
                    <span className="ml-auto text-[9px] font-bold tracking-widest text-gold uppercase px-1 py-0.5 rounded border border-gold/40 bg-gold/10">
                      ACTIVE
                    </span>
                  )}
                </div>
                {rp.key !== "custom" ? (
                  <div className="grid grid-cols-3 gap-1 text-center mt-1">
                    {[
                      { label: "Cap", val: `${rp.capital}%` },
                      { label: "TP",  val: `+${rp.tp}%` },
                      { label: "SL",  val: `-${rp.sl}%` },
                    ].map(({ label, val }) => (
                      <div key={label} className="bg-surface-2 rounded px-1 py-0.5">
                        <div className="text-[9px] text-ink-4 uppercase">{label}</div>
                        <div className="text-xs font-mono font-bold text-ink-1">{val}</div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="mt-2 space-y-1.5" onClick={e => e.stopPropagation()}>
                    <div className="grid grid-cols-3 gap-2">
                      {[
                        { label: "Capital %", val: customCapital, set: setCustomCapital, max: 80 },
                        { label: "TP %",      val: customTp,      set: setCustomTp,      max: 99 },
                        { label: "SL %",      val: customSl,      set: setCustomSl,      max: 99 },
                      ].map(({ label, val, set }) => (
                        <div key={label}>
                          <label className="text-[9px] text-ink-4 uppercase block mb-0.5">{label}</label>
                          <input
                            type="number"
                            min={1}
                            max={99}
                            value={val}
                            onChange={e => set(e.target.value)}
                            className="w-full bg-surface-3 border border-ink-4 rounded px-1.5 py-1 text-xs font-mono text-ink-1 focus:border-gold focus:outline-none"
                          />
                        </div>
                      ))}
                    </div>
                    {customErr && (
                      <p className="text-xs text-red-400">{customErr}</p>
                    )}
                    <button
                      onClick={() => void handleSaveCustomRisk()}
                      disabled={savingRisk}
                      className="w-full mt-1 py-1.5 rounded bg-gold/20 border border-gold/40 text-gold text-xs font-bold hover:bg-gold/30 disabled:opacity-50"
                    >
                      {savingRisk ? "Saving…" : "Save Custom Profile"}
                    </button>
                  </div>
                )}
              </button>
            );
          })}
        </div>

      </div>
    </>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between mt-4 mb-2 mx-0.5">
      <div className="font-hud text-[10px] font-bold tracking-[3px] text-ink-2 uppercase flex items-center gap-2">
        <span className="w-3 h-px bg-gold" aria-hidden />
        {children}
      </div>
    </div>
  );
}
