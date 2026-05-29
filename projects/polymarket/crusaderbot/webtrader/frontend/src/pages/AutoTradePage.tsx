import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { CopyTradePage, PageTabs } from "./CopyTradePage";
import { CollapsibleSection } from "../components/CollapsibleSection";
import { DesktopPageHeader } from "../components/DesktopPageHeader";
import { HeroCard } from "../components/HeroCard";
import { TopBar } from "../components/TopBar";
import { makeApi, type AutoTradeState, type CustomizeParams, type MarketFilterSettings, type RiskProfileParams, type TradingSettings } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useSSE } from "../lib/sse";

const ALL_CATEGORIES = ["Politics","Sports","Crypto","Finance","Science","Entertainment","World","Weather","Other"];

// ── Section A: Strategy Presets ───────────────────────────────────────────────
// Mirrors VISIBLE_PRESET_ORDER in domain/preset/presets.py.
// Only presets validated in production are selectable. Hidden presets are shown
// as "coming soon" cards for visibility but cannot be activated.

const STRATEGY_PRESETS = [
  {
    key: "close_sweep",
    name: "Close Sweep",
    emoji: "🧹",
    engine: "W.A.R.P_STRIKE",
    signal: "Final 35s entry on BTC/ETH/SOL candles. Strong lean required.",
    risk: "safe" as const,
    freq: "Medium",
    visible: true,
  },
  {
    key: "safe_close",
    name: "Safe Close",
    emoji: "🔒",
    engine: "W.A.R.P_STRIKE",
    signal: "Entry 30–60s before close. Tighter lean filter, fewer but cleaner entries.",
    risk: "safe" as const,
    freq: "Low",
    visible: true,
  },
  {
    key: "flip_hunter",
    name: "Flip Hunter",
    emoji: "🎯",
    engine: "W.A.R.P_STRIKE",
    signal: "Early 140s entry on cheap side (0.26–0.35). Asymmetric upside on flips.",
    risk: "advanced" as const,
    freq: "Low",
    visible: true,
  },
] as const;

// No presets currently locked — all candle presets are active.
const COMING_SOON_PRESETS: readonly {
  key: string;
  name: string;
  emoji: string;
  signal: string;
  risk: "safe" | "balanced" | "advanced" | "aggressive";
}[] = [];

// All candle presets route to W.A.R.P_STRIKE engine on short-duration crypto markets.
// Selecting one locks the market category to Crypto and surfaces the 5m/15m toggle.
const CRYPTO_SHORT_PRESETS: readonly string[] = ["close_sweep", "safe_close", "flip_hunter"];
const TIMEFRAMES = ["5m", "15m"] as const;
type Timeframe = (typeof TIMEFRAMES)[number];
const CRYPTO_ASSETS = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "HYPE"] as const;
// Default active selection for a fresh crypto-short preset: BTC only. The other
// assets are opt-in — their candle books are thinner, so leaving them off by
// default avoids "selected but never fills" on the low-liquidity tickers.
const CRYPTO_ASSETS_DEFAULT: readonly string[] = ["BTC"];

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
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const tab = searchParams.get("tab") ?? "auto";
  const marketName = searchParams.get("market_name") ?? null;
  const [state, setState] = useState<AutoTradeState | null>(null);
  const [tradingMode, setTradingMode] = useState<string>("paper");
  const [loading, setLoading] = useState(false);

  // Custom risk inputs
  const [customCapital, setCustomCapital] = useState("20");
  const [customTp, setCustomTp]           = useState("15");
  const [customSl, setCustomSl]           = useState("10");
  const [customErr, setCustomErr]         = useState<string | null>(null);
  const [savingRisk, setSavingRisk]       = useState(false);

  // Market filter state
  const [filterCats, setFilterCats]           = useState<string[]>(ALL_CATEGORIES);
  const [filterLiquidity, setFilterLiquidity] = useState<string>("1000");
  const [filterResolution, setFilterResolution] = useState<string>("0");
  const [filterVolume, setFilterVolume]       = useState<string>("100");
  const [filterSlippage, setFilterSlippage]   = useState<string>("3");
  const [savingFilters, setSavingFilters]     = useState(false);
  const [filterSaved, setFilterSaved]         = useState(false);
  // Crypto-short preset config (assets shown inline inside the active card)
  const [selectedAssets, setSelectedAssets]   = useState<string[]>([...CRYPTO_ASSETS_DEFAULT]);

  const load = useCallback(async () => {
    const [autotradeResult, dashResult] = await Promise.allSettled([
      api.getAutotrade(),
      api.getDashboard(),
    ]);
    if (autotradeResult.status === "rejected") throw autotradeResult.reason;
    const s = autotradeResult.value;
    setState(s);
    if (dashResult.status === "fulfilled") setTradingMode(dashResult.value.trading_mode);
    if (s.risk_profile === "custom") {
      setCustomCapital(String(Math.round((s.capital_alloc_pct ?? 0) * 100)));
      // TP/SL may be null (custom TP-only or SL-only) — show blank, not "0".
      setCustomTp(s.tp_pct != null ? String(Math.round(s.tp_pct * 100)) : "");
      setCustomSl(s.sl_pct != null ? String(Math.round(s.sl_pct * 100)) : "");
    }
    if (s.market_categories) setFilterCats(s.market_categories);
    if (s.min_liquidity != null) setFilterLiquidity(String(s.min_liquidity));
    if (s.max_resolution_days != null) setFilterResolution(String(s.max_resolution_days));
    if (s.min_volume_24h != null) setFilterVolume(String(s.min_volume_24h));
    if (s.slippage_tolerance_pct != null) setFilterSlippage(String(Math.round(s.slippage_tolerance_pct * 100)));
    if (s.selected_assets && s.selected_assets.length > 0) setSelectedAssets(s.selected_assets);
    else setSelectedAssets([...CRYPTO_ASSETS_DEFAULT]);
  }, [api]);

  useEffect(() => { void load(); }, [load]);
  // Poll every 30s to catch changes from Telegram bot (auto_trade_on lives in users
  // table which has no pg_notify trigger, so SSE alone is not sufficient).
  useEffect(() => {
    const id = setInterval(() => { void load(); }, 30_000);
    return () => clearInterval(id);
  }, [load]);
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
    if (CRYPTO_SHORT_PRESETS.includes(key)) {
      // Crypto-short presets carry a timeframe + asset selection.
      const tf = (state?.selected_timeframe as Timeframe) ?? "5m";
      const assets = selectedAssets.length > 0 ? selectedAssets : [...CRYPTO_ASSETS_DEFAULT];
      await api.activatePreset(key, tf, assets);
    } else {
      await api.activatePreset(key);
    }
    await load();
  }

  async function handleSelectTimeframe(tf: Timeframe) {
    if (!state?.active_preset) return;
    const assets = selectedAssets.length > 0 ? selectedAssets : [...CRYPTO_ASSETS_DEFAULT];
    await api.activatePreset(state.active_preset, tf, assets);
    await load();
  }

  async function handleToggleAsset(asset: string) {
    if (!state?.active_preset) return;
    // Keep at least one asset selected.
    const next = selectedAssets.includes(asset)
      ? selectedAssets.filter(a => a !== asset)
      : [...selectedAssets, asset];
    if (next.length === 0) return;
    setSelectedAssets(next);
    const tf = (state.selected_timeframe as Timeframe) ?? "5m";
    await api.activatePreset(state.active_preset, tf, next);
    await load();
  }

  async function handleActivateRisk(profile: RiskProfileParams["profile"]) {
    if (profile === "custom") return; // custom handled by save button
    await api.setRiskProfile({ profile });
    await load();
  }

  async function handleSaveFilters() {
    setSavingFilters(true);
    try {
      const filterPayload: MarketFilterSettings = {
        market_categories: filterCats,
        min_liquidity: parseFloat(filterLiquidity),
        max_resolution_days: filterResolution === "0" ? null : parseInt(filterResolution, 10),
        min_volume_24h: parseFloat(filterVolume),
      };
      const slippageNum = parseFloat(filterSlippage);
      const tradingPayload: TradingSettings = {};
      if (!isNaN(slippageNum) && slippageNum >= 0 && slippageNum <= 100) {
        tradingPayload.slippage_tolerance_pct = slippageNum / 100;
      }
      await Promise.all([
        api.updateMarketFilters(filterPayload),
        Object.keys(tradingPayload).length > 0
          ? api.updateTradingSettings(tradingPayload)
          : Promise.resolve(),
      ]);
      setFilterSaved(true);
      setTimeout(() => setFilterSaved(false), 2000);
    } finally {
      setSavingFilters(false);
    }
  }

  function toggleCategory(cat: string) {
    setFilterCats(prev =>
      prev.includes(cat) ? prev.filter(c => c !== cat) : [...prev, cat]
    );
  }

  async function handleSaveCustomRisk() {
    setCustomErr(null);
    const cap = parseFloat(customCapital) / 100;
    // TP and SL are each OPTIONAL — leave one blank to disable that side
    // (TP-only or SL-only). At least one is required.
    const tpRaw = customTp.trim();
    const slRaw = customSl.trim();
    const tp = tpRaw === "" ? null : parseFloat(tpRaw) / 100;
    const sl = slRaw === "" ? null : parseFloat(slRaw) / 100;
    if (isNaN(cap)) {
      setCustomErr("Enter a valid Capital %.");
      return;
    }
    if (cap > 0.80) {
      setCustomErr("Capital may not exceed 80%.");
      return;
    }
    if (tp === null && sl === null) {
      setCustomErr("Set at least one of Take Profit or Stop Loss.");
      return;
    }
    if (tp !== null && isNaN(tp)) { setCustomErr("Take Profit must be a number or blank."); return; }
    if (sl !== null && isNaN(sl)) { setCustomErr("Stop Loss must be a number or blank."); return; }
    // Only enforce ordering when BOTH are set.
    if (tp !== null && sl !== null && tp <= sl) {
      setCustomErr("Take Profit must be greater than Stop Loss.");
      return;
    }
    setSavingRisk(true);
    try {
      await api.setRiskProfile({
        profile: "custom",
        capital_alloc_pct: cap,
        tp_pct: tp ?? undefined,
        sl_pct: sl ?? undefined,
      });
      await load();
    } catch (e: unknown) {
      setCustomErr(e instanceof Error ? e.message : "Save failed.");
    } finally {
      setSavingRisk(false);
    }
  }

  // All hooks declared above — safe to early-return here
  if (tab === "copy") return <CopyTradePage />;

  if (!state) return (
    <>
      <TopBar />
      <div className="p-4 text-ink-3 text-sm font-mono">Loading…</div>
    </>
  );

  const activeStrategy = STRATEGY_PRESETS.find(p => p.key === state.active_preset);
  const heroValue = activeStrategy ? activeStrategy.name.toUpperCase() : "IDLE";
  const isCryptoShortActive =
    !!state.active_preset && CRYPTO_SHORT_PRESETS.includes(state.active_preset);
  const activeTimeframe = (state.selected_timeframe as Timeframe | null) ?? "5m";

  return (
    <>
      <TopBar tradingMode={tradingMode} />
      <PageTabs active="auto" onSwitch={(t) => navigate(t === "copy" ? "/autotrade?tab=copy" : "/autotrade")} />
      <div className="px-3.5 pt-2 pb-6 animate-page-in">

        {/* Market context banner — shown when navigated from Discover page */}
        {marketName && (
          <div className="mb-3 px-3 py-2 rounded border border-gold/30 bg-gold/5 flex items-center gap-2">
            <span className="text-gold text-[11px]">🎯</span>
            <p className="text-[10px] font-mono text-ink-2">
              Configuring for: <span className="text-gold font-bold">{marketName}</span>
            </p>
          </div>
        )}

        {/* Paper Mode reassurance — only shown when backend confirms paper mode */}
        {tradingMode !== "live" && (
          <div
            className="mb-3 px-3 py-2 flex items-center gap-2 text-[10px] font-mono font-bold tracking-[1.5px] clip-card border"
            style={{
              background: "rgba(245,200,66,0.04)",
              borderColor: "rgba(245,200,66,0.15)",
              color: "var(--gold,#F5C842)",
            }}
            role="status"
          >
            <span style={{ fontSize: "12px" }}>🛡</span>
            PAPER MODE — No real funds at risk · all trades are simulated
          </div>
        )}

        {/* Desktop page header — hidden on mobile */}
        <DesktopPageHeader
          title={<>AUTO <span className="text-gold">TRADE</span></>}
          subtitle="SELECT STRATEGY · RISK PROFILE · MARKET FILTER"
        />

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

        <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
          {STRATEGY_PRESETS.map((p) => {
            const isActive = state.active_preset === p.key;
            // When the operator has globally disabled this strategy, the preset
            // is still "selected" but fires no new trades → show PAUSED (Admin).
            const isGloballyPaused = isActive && state.active_preset_globally_enabled === false;
            const showConfig = isActive && CRYPTO_SHORT_PRESETS.includes(p.key);
            return (
              <Fragment key={p.key}>
                <button
                  onClick={() => void handleActivatePreset(p.key)}
                  className={[
                    "w-full text-left p-3 rounded-lg border transition-all",
                    showConfig ? "rounded-b-none" : "",
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
                            <span
                              className={[
                                "text-[9px] font-bold tracking-widest uppercase px-1.5 py-0.5 rounded border",
                                isGloballyPaused
                                  ? "text-ink-4 border-ink-3 bg-surface-2"
                                  : "text-gold border-gold/40 bg-gold/10",
                              ].join(" ")}
                            >
                              {isGloballyPaused ? "PAUSED (ADMIN)" : "ACTIVE"}
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

                {/* Inline config for crypto-short presets: assets + timeframe */}
                {showConfig && (
                  <div className="md:col-span-3 p-3 rounded-lg rounded-t-none border border-t-0 border-gold/40 bg-surface-2">
                    <div className="flex items-center justify-between gap-2 mb-2">
                      <p className="text-[9px] text-ink-4 uppercase tracking-[1.5px] font-mono">Assets</p>
                      <span className="text-[9px] font-bold tracking-widest text-gold uppercase px-1.5 py-0.5 rounded border border-gold/40 bg-gold/10">
                        Crypto only
                      </span>
                    </div>
                    <div className="grid grid-cols-4 gap-2 mb-3">
                      {CRYPTO_ASSETS.map((asset) => {
                        const on = selectedAssets.includes(asset);
                        return (
                          <button
                            key={asset}
                            onClick={() => void handleToggleAsset(asset)}
                            className={[
                              "py-2 rounded-lg border text-xs font-hud font-bold transition-all",
                              on
                                ? "border-gold bg-gold/10 text-gold"
                                : "border-surface-3 bg-surface-1 text-ink-3 hover:border-ink-3",
                            ].join(" ")}
                          >
                            {asset}
                          </button>
                        );
                      })}
                    </div>
                    <p className="text-[9px] text-ink-4 uppercase tracking-[1.5px] font-mono mb-2">Timeframe</p>
                    <div className="grid grid-cols-2 gap-2">
                      {TIMEFRAMES.map((tf) => {
                        const tfActive = activeTimeframe === tf;
                        return (
                          <button
                            key={tf}
                            onClick={() => void handleSelectTimeframe(tf)}
                            className={[
                              "py-2 rounded-lg border text-sm font-hud font-bold transition-all",
                              tfActive
                                ? "border-gold bg-gold/10 text-gold shadow-[0_0_8px_rgba(191,155,48,0.25)]"
                                : "border-surface-3 bg-surface-1 text-ink-2 hover:border-ink-3",
                            ].join(" ")}
                          >
                            {tf}
                          </button>
                        );
                      })}
                    </div>
                    <p className="text-[10px] text-ink-4 font-mono mt-2">
                      Trades only {selectedAssets.join("/")} short-duration markets ({activeTimeframe}). Category locked to Crypto.
                    </p>
                  </div>
                )}
              </Fragment>
            );
          })}

          {/* Coming-soon presets — locked, not selectable */}
          {COMING_SOON_PRESETS.map((p) => (
            <div
              key={p.key}
              className="w-full text-left p-3 rounded-lg border border-surface-3 bg-surface-1 opacity-50 cursor-not-allowed select-none"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-lg">{p.emoji}</span>
                  <div className="min-w-0">
                    <div className="font-hud text-sm font-bold text-ink-2 flex items-center gap-2">
                      {p.name}
                      <span className="text-[9px] font-bold tracking-widest text-ink-4 uppercase px-1.5 py-0.5 rounded border border-surface-3 bg-surface-2">
                        SOON
                      </span>
                    </div>
                    <div className="text-xs text-ink-4 truncate mt-0.5">{p.signal}</div>
                  </div>
                </div>
                <div className="text-right shrink-0 text-xs text-ink-4">
                  <div className={`font-bold ${riskColor[p.risk]} uppercase opacity-60`}>{p.risk}</div>
                </div>
              </div>
            </div>
          ))}

        </div>

        {/* ── SECTION B: Risk Profile ── */}
        <SectionTitle>Risk Profile</SectionTitle>
        <p className="text-ink-3 text-xs font-mono mb-2 mx-0.5">
          Controls capital %, take profit, and stop loss. Applies to all trade types.
        </p>
        {/* CAP% is the deployable POOL, not the per-trade size. Surface the real
            max-per-trade so users don't read "60%" as "$600 per trade". */}
        {state.effective_max_per_trade_usdc != null && (
          <p className="text-[11px] font-mono mb-2 mx-0.5 px-2 py-1.5 rounded border border-gold/30 bg-gold/5 text-ink-2">
            <span className="text-gold font-bold">Max per trade: ${state.effective_max_per_trade_usdc.toFixed(2)}</span>
            {state.equity_usdc != null && (
              <span className="text-ink-3"> · CAP {Math.round(state.capital_alloc_pct * 100)}% of ${state.equity_usdc.toFixed(2)} equity is the deployable pool, not one trade</span>
            )}
          </p>
        )}
        <MaxPerTradeControl state={state} api={api} onSaved={() => void load()} />
        <DailyLossControl state={state} api={api} onSaved={() => void load()} />
        <MaxDrawdownControl state={state} api={api} onSaved={() => void load()} />


        {/* 3 preset cards — equal width row */}
        <div className="grid grid-cols-3 gap-2 mb-2">
          {RISK_PROFILES.filter(rp => rp.key !== "custom").map((rp) => {
            const isActive = state.risk_profile === rp.key;
            return (
              <button
                key={rp.key}
                onClick={() => void handleActivateRisk(rp.key)}
                className={[
                  "text-left p-2.5 rounded-lg border transition-all",
                  isActive
                    ? "border-gold bg-surface-2 shadow-[0_0_10px_rgba(245,200,66,0.15)]"
                    : "border-border-1 bg-surface-1 hover:border-border-3",
                ].join(" ")}
              >
                <div className="flex items-center gap-1 mb-1.5">
                  <span className="text-[13px]">{rp.emoji}</span>
                  <span className="font-hud text-[9px] font-bold text-ink-1 leading-none">{rp.name}</span>
                </div>
                {isActive && (
                  <div className="mb-1.5">
                    <span className="text-[8px] font-bold tracking-widest text-gold uppercase px-1 py-0.5 rounded border border-gold/40 bg-gold/10">
                      ACTIVE
                    </span>
                  </div>
                )}
                <div className="space-y-1">
                  {[
                    { label: "CAP", val: `${rp.capital}%` },
                    { label: "TP",  val: `+${rp.tp}%` },
                    { label: "SL",  val: `-${rp.sl}%` },
                  ].map(({ label, val }) => (
                    <div key={label} className="flex justify-between items-center">
                      <span className="text-[8px] text-ink-4 font-mono uppercase">{label}</span>
                      <span className="text-[10px] font-mono font-bold text-ink-1">{val}</span>
                    </div>
                  ))}
                </div>
              </button>
            );
          })}
        </div>

        {/* Custom Risk — full-width, separate block */}
        {(() => {
          const rp = RISK_PROFILES.find(r => r.key === "custom")!;
          const isActive = state.risk_profile === "custom";
          return (
            <div
              className={[
                "p-3 rounded-lg border transition-all",
                isActive
                  ? "border-gold/60 bg-surface-2"
                  : "border-border-1 bg-surface-1",
              ].join(" ")}
            >
              <div className="flex items-center gap-2 mb-2.5">
                <span className="text-[14px]">{rp.emoji}</span>
                <span className="font-hud text-[10px] font-bold text-ink-1">{rp.name}</span>
                {isActive && (
                  <span className="ml-auto text-[8px] font-bold tracking-widest text-gold uppercase px-1.5 py-0.5 rounded border border-gold/40 bg-gold/10">
                    ACTIVE
                  </span>
                )}
              </div>
              <div className="grid grid-cols-3 gap-2 mb-1" onClick={e => e.stopPropagation()}>
                {[
                  { label: "Capital %", val: customCapital, set: setCustomCapital, ph: "20" },
                  { label: "TP % (opt)", val: customTp,      set: setCustomTp,      ph: "—"  },
                  { label: "SL % (opt)", val: customSl,      set: setCustomSl,      ph: "—"  },
                ].map(({ label, val, set, ph }) => (
                  <div key={label}>
                    <label className="text-[9px] text-ink-4 uppercase block mb-0.5 font-mono">{label}</label>
                    <input
                      type="number"
                      min={1}
                      max={99}
                      value={val}
                      placeholder={ph}
                      onChange={e => set(e.target.value)}
                      className="w-full bg-surface border border-border-2 rounded px-2 py-1.5 text-xs font-mono text-ink-1 placeholder:text-ink-4 focus:border-gold focus:outline-none"
                    />
                  </div>
                ))}
              </div>
              <p className="text-[8px] text-ink-4 font-mono mb-2">Leave TP or SL blank to use only one. At least one required.</p>
              {customErr && <p className="text-xs text-red mb-2">{customErr}</p>}
              <button
                onClick={() => void handleSaveCustomRisk()}
                disabled={savingRisk}
                className="w-full py-2 rounded border border-gold/40 bg-gold/10 text-gold text-[10px] font-bold tracking-[1.5px] uppercase hover:bg-gold/20 disabled:opacity-50 transition-colors"
              >
                {savingRisk ? "Saving…" : "Save Custom Profile"}
              </button>
            </div>
          );
        })()}

        {/* ── SECTION C: Market Filter ── */}
        <CollapsibleSection id="autotrade_market_filter" label="Market Filter" defaultOpen={true}>
        <p className="text-ink-3 text-xs font-mono mb-3 mx-0.5">
          Choose which market categories and liquidity thresholds the bot scans.
        </p>

        <div className="p-3 rounded-lg border border-surface-3 bg-surface-1 space-y-3">
          {/* Categories */}
          <div>
            <p className="text-[9px] text-ink-4 uppercase tracking-[1.5px] font-mono mb-2">Categories</p>
            {isCryptoShortActive && (
              <p className="text-[10px] text-gold font-mono mb-2">
                Locked to Crypto by the active {activeStrategy?.name ?? "strategy"} preset.
              </p>
            )}
            <div className="grid grid-cols-3 gap-1.5">
              {ALL_CATEGORIES.map((cat) => {
                const on = filterCats.includes(cat);
                return (
                  <label
                    key={cat}
                    className={[
                      "flex items-center gap-1.5 px-2 py-1.5 rounded border text-[10px] font-mono transition-colors",
                      isCryptoShortActive
                        ? "cursor-not-allowed opacity-50"
                        : "cursor-pointer",
                      on
                        ? "border-gold/50 bg-gold/10 text-gold"
                        : "border-surface-3 bg-surface-2 text-ink-3 hover:border-ink-3",
                    ].join(" ")}
                  >
                    <input
                      type="checkbox"
                      checked={on}
                      disabled={isCryptoShortActive}
                      onChange={() => toggleCategory(cat)}
                      className="accent-gold w-3 h-3 shrink-0"
                    />
                    {cat}
                  </label>
                );
              })}
            </div>
          </div>

          {/* Dropdowns */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
            <div>
              <label className="text-[9px] text-ink-4 uppercase tracking-[1.5px] font-mono block mb-1">Min Liquidity</label>
              <select
                value={filterLiquidity}
                onChange={e => setFilterLiquidity(e.target.value)}
                className="w-full bg-surface-3 border border-surface-3 rounded px-2 py-1.5 text-xs font-mono text-ink-1 focus:border-gold focus:outline-none"
              >
                <option value="1000">$1k</option>
                <option value="5000">$5k</option>
                <option value="10000">$10k</option>
                <option value="50000">$50k</option>
              </select>
            </div>
            <div>
              <label className="text-[9px] text-ink-4 uppercase tracking-[1.5px] font-mono block mb-1">Max Time to Resolution</label>
              <select
                value={filterResolution}
                onChange={e => setFilterResolution(e.target.value)}
                className="w-full bg-surface-3 border border-surface-3 rounded px-2 py-1.5 text-xs font-mono text-ink-1 focus:border-gold focus:outline-none"
              >
                <option value="0">Any</option>
                <option value="1">1 day</option>
                <option value="7">7 days</option>
                <option value="30">30 days</option>
                <option value="90">90 days</option>
              </select>
            </div>
            <div>
              <label className="text-[9px] text-ink-4 uppercase tracking-[1.5px] font-mono block mb-1">Min Volume 24h</label>
              <select
                value={filterVolume}
                onChange={e => setFilterVolume(e.target.value)}
                className="w-full bg-surface-3 border border-surface-3 rounded px-2 py-1.5 text-xs font-mono text-ink-1 focus:border-gold focus:outline-none"
              >
                <option value="100">$100</option>
                <option value="500">$500</option>
                <option value="1000">$1k</option>
                <option value="5000">$5k</option>
              </select>
            </div>
          </div>

          {/* Slippage Tolerance */}
          <div>
            <label className="text-[9px] text-ink-4 uppercase tracking-[1.5px] font-mono block mb-1">
              Slippage Tolerance
            </label>
            <div className="flex items-center gap-2">
              <input
                type="number"
                min={0}
                max={100}
                step={0.5}
                value={filterSlippage}
                onChange={e => setFilterSlippage(e.target.value)}
                className="w-20 bg-surface-3 border border-surface-3 rounded px-2 py-1.5 text-xs font-mono text-ink-1 placeholder:text-ink-3 focus:border-gold focus:outline-none"
                style={{ color: "white" }}
                placeholder="3"
              />
              <span className="text-ink-3 font-mono text-xs">%</span>
              {parseFloat(filterSlippage) > 3 && (
                <span className="text-[10px] font-mono" style={{ color: "#F5C842" }}>
                  ⚠ High — may get poor fills on thin markets
                </span>
              )}
            </div>
          </div>

          <button
            onClick={() => void handleSaveFilters()}
            disabled={savingFilters}
            className="w-full py-1.5 rounded bg-gold/20 border border-gold/40 text-gold text-xs font-bold hover:bg-gold/30 disabled:opacity-50 transition-colors"
          >
            {filterSaved ? "✓ Saved" : savingFilters ? "Saving…" : "Save Market Filters"}
          </button>
        </div>
        </CollapsibleSection>

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

// ── Max per trade control ─────────────────────────────────────────────────────
// Lets a user cap the $ size of any single trade in one of two modes (or leave
// it on the system default). Hard system limits ($1–$500 / 0.5–10% of equity)
// are re-enforced server-side at sizing time, so this can only tighten risk
// within those bounds. CAP% remains the deployable pool, not the trade size.
function MaxPerTradeControl({ state, api, onSaved }: {
  state: AutoTradeState;
  api: ReturnType<typeof makeApi>;
  onSaved: () => void;
}) {
  const [mode, setMode] = useState<"auto" | "fixed" | "pct">(state.max_per_trade_mode ?? "auto");
  const [usd, setUsd] = useState(state.max_per_trade_usdc != null ? String(state.max_per_trade_usdc) : "");
  const [pct, setPct] = useState(state.max_per_trade_pct != null ? String(Math.round(state.max_per_trade_pct * 100)) : "");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  async function save() {
    setSaving(true);
    try {
      const params: CustomizeParams = { max_per_trade_mode: mode };
      if (mode === "fixed") params.max_per_trade_usdc = Math.max(1, Math.min(500, Number(usd) || 0));
      if (mode === "pct") params.max_per_trade_pct = Math.max(0.005, Math.min(0.10, (Number(pct) || 0) / 100));
      await api.customizeStrategy(params);
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
      onSaved();
    } finally {
      setSaving(false);
    }
  }

  const MODES: { key: "auto" | "fixed" | "pct"; label: string }[] = [
    { key: "auto", label: "Auto ($25)" },
    { key: "fixed", label: "Fixed $" },
    { key: "pct", label: "% Equity" },
  ];

  return (
    <div className="mb-3 mx-0.5 p-2.5 rounded-lg border border-surface-3 bg-surface-1">
      <p className="text-[9px] text-ink-4 uppercase tracking-[1.5px] font-mono mb-2">Max per trade</p>
      <div className="grid grid-cols-3 gap-2 mb-2">
        {MODES.map((m) => (
          <button
            key={m.key}
            onClick={() => setMode(m.key)}
            className={[
              "py-1.5 rounded-md border text-[11px] font-hud font-bold transition-all",
              mode === m.key ? "border-gold bg-gold/10 text-gold" : "border-surface-3 bg-surface-2 text-ink-3 hover:border-ink-3",
            ].join(" ")}
          >
            {m.label}
          </button>
        ))}
      </div>
      {mode === "fixed" && (
        <input
          type="number" inputMode="decimal" min={1} max={500} value={usd}
          onChange={(e) => setUsd(e.target.value)}
          placeholder="$ per trade (1–500)"
          className="w-full mb-2 px-2 py-1.5 rounded-md bg-surface-2 border border-surface-3 text-ink-1 text-xs font-mono"
        />
      )}
      {mode === "pct" && (
        <input
          type="number" inputMode="decimal" min={0.5} max={10} step={0.5} value={pct}
          onChange={(e) => setPct(e.target.value)}
          placeholder="% of equity (0.5–10)"
          className="w-full mb-2 px-2 py-1.5 rounded-md bg-surface-2 border border-surface-3 text-ink-1 text-xs font-mono"
        />
      )}
      <button
        onClick={() => void save()}
        disabled={saving}
        className="w-full py-1.5 rounded-md border border-gold/40 bg-gold/10 text-gold text-[11px] font-hud font-bold tracking-[1.5px] uppercase disabled:opacity-50"
      >
        {saved ? "Saved ✓" : saving ? "Saving…" : "Save Max Per Trade"}
      </button>
    </div>
  );
}


// ── DailyLossControl ──────────────────────────────────────────────────────────
// Exposes user_settings.daily_loss_override. The effective cap is the most
// restrictive of: system -$2000, profile default, and user override.
function DailyLossControl({ state, api, onSaved }: {
  state: AutoTradeState;
  api: ReturnType<typeof makeApi>;
  onSaved: () => void;
}) {
  const PROFILE_DEFAULTS: Record<string, number> = {
    conservative: -200, balanced: -500, aggressive: -1000, custom: -500,
  };
  const profileFloor = PROFILE_DEFAULTS[state.risk_profile] ?? -500;
  const current = state.daily_loss_override ?? null;
  const [val, setVal] = useState(current != null ? String(Math.abs(current)) : "");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  async function save() {
    const raw = Number(val);
    if (!val || isNaN(raw) || raw <= 0) return;
    const override = -Math.min(raw, 2000);  // always negative, bounded to -$2000
    setSaving(true);
    try {
      await api.customizeStrategy({ daily_loss_override: override });
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
      onSaved();
    } finally {
      setSaving(false);
    }
  }

  async function clear() {
    setSaving(true);
    try {
      await api.customizeStrategy({ daily_loss_override: null });
      setVal("");
      onSaved();
    } finally {
      setSaving(false);
    }
  }

  const effective = current != null
    ? Math.max(profileFloor, current)   // most restrictive (less negative wins)
    : profileFloor;

  return (
    <div className="mb-3 mx-0.5 p-2.5 rounded-lg border border-surface-3 bg-surface-1">
      <p className="text-[9px] text-ink-4 uppercase tracking-[1.5px] font-mono mb-1">Daily Loss Limit</p>
      <p className="text-[10px] text-ink-3 font-mono mb-2">
        Halt trading when daily P&amp;L drops below this. Profile default: <span className="text-ink-1">${Math.abs(profileFloor)}</span>.
        Effective: <span className="text-grn font-bold">${Math.abs(effective)}</span>
        {current != null && current > profileFloor && (
          <span className="text-ink-4"> (your override)</span>
        )}
      </p>
      <div className="flex gap-2 mb-2">
        <span className="flex items-center text-xs text-ink-3 font-mono">-$</span>
        <input
          type="number" inputMode="decimal" min={1} max={2000} value={val}
          onChange={(e) => setVal(e.target.value)}
          placeholder={`e.g. ${Math.abs(profileFloor)} (profile default)`}
          className="flex-1 px-2 py-1.5 rounded-md bg-surface-2 border border-surface-3 text-ink-1 text-xs font-mono"
        />
      </div>
      <div className="flex gap-2">
        <button
          onClick={() => void save()}
          disabled={saving || !val}
          className="flex-1 py-1.5 rounded-md border border-gold/40 bg-gold/10 text-gold text-[11px] font-hud font-bold tracking-[1.5px] uppercase disabled:opacity-50"
        >
          {saved ? "Saved ✓" : saving ? "Saving…" : "Set Limit"}
        </button>
        {current != null && (
          <button
            onClick={() => void clear()}
            disabled={saving}
            className="px-3 py-1.5 rounded-md border border-surface-3 bg-surface-2 text-ink-3 text-[11px] font-hud disabled:opacity-50"
          >
            Reset
          </button>
        )}
      </div>
    </div>
  );
}


// ── MaxDrawdownControl ────────────────────────────────────────────────────────
// Exposes user_settings.max_drawdown_pct (0, 0.08]. System 8% applies regardless;
// this only lets users halt *earlier* (stricter drawdown fence).
function MaxDrawdownControl({ state, api, onSaved }: {
  state: AutoTradeState;
  api: ReturnType<typeof makeApi>;
  onSaved: () => void;
}) {
  const current = state.max_drawdown_pct ?? null;
  const [val, setVal] = useState(current != null ? String(Math.round(current * 100)) : "");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  async function save() {
    const raw = Number(val);
    if (!val || isNaN(raw) || raw <= 0 || raw > 8) return;
    const pct = Math.min(raw / 100, 0.08);
    setSaving(true);
    try {
      await api.customizeStrategy({ max_drawdown_pct: pct });
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
      onSaved();
    } finally {
      setSaving(false);
    }
  }

  async function clear() {
    setSaving(true);
    try {
      await api.customizeStrategy({ max_drawdown_pct: null });
      setVal("");
      onSaved();
    } finally {
      setSaving(false);
    }
  }

  const effectivePct = current != null ? Math.min(current, 0.08) : 0.08;

  return (
    <div className="mb-3 mx-0.5 p-2.5 rounded-lg border border-surface-3 bg-surface-1">
      <p className="text-[9px] text-ink-4 uppercase tracking-[1.5px] font-mono mb-1">Max Drawdown Halt</p>
      <p className="text-[10px] text-ink-3 font-mono mb-2">
        Auto-halt when account drawdown exceeds this. System max: <span className="text-ink-1">8%</span>.
        Effective: <span className="text-grn font-bold">{(effectivePct * 100).toFixed(0)}%</span>
        {current != null && current < 0.08 && (
          <span className="text-ink-4"> (your override)</span>
        )}
      </p>
      <div className="flex gap-2 mb-2">
        <input
          type="number" inputMode="decimal" min={1} max={8} step={1} value={val}
          onChange={(e) => setVal(e.target.value)}
          placeholder="% (1–8, system max 8%)"
          className="flex-1 px-2 py-1.5 rounded-md bg-surface-2 border border-surface-3 text-ink-1 text-xs font-mono"
        />
        <span className="flex items-center text-xs text-ink-3 font-mono">%</span>
      </div>
      <div className="flex gap-2">
        <button
          onClick={() => void save()}
          disabled={saving || !val}
          className="flex-1 py-1.5 rounded-md border border-gold/40 bg-gold/10 text-gold text-[11px] font-hud font-bold tracking-[1.5px] uppercase disabled:opacity-50"
        >
          {saved ? "Saved ✓" : saving ? "Saving…" : "Set Drawdown Halt"}
        </button>
        {current != null && (
          <button
            onClick={() => void clear()}
            disabled={saving}
            className="px-3 py-1.5 rounded-md border border-surface-3 bg-surface-2 text-ink-3 text-[11px] font-hud disabled:opacity-50"
          >
            Reset
          </button>
        )}
      </div>
    </div>
  );
}
