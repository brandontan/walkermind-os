import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AdvancedOnly } from "../components/AdvancedGate";
import { DesktopPageHeader } from "../components/DesktopPageHeader";
import { SettingsGroup, SettingsRow } from "../components/SettingsGroup";
import { Toggle } from "../components/Toggle";
import { TopBar } from "../components/TopBar";
import { makeApi, type UserSettings } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useUiMode } from "../lib/uiMode";

export function SettingsPage() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const api = useMemo(() => makeApi(user?.token ?? null), [user?.token]);
  const { advanced, toggle: toggleAdvanced } = useUiMode();
  const [settings, setSettings] = useState<UserSettings | null>(null);
  const [tradingMode, setTradingMode] = useState<string>("paper");

  // Auto-redeem local state
  const [autoRedeem, setAutoRedeem] = useState(false);
  const [redeemMode, setRedeemMode] = useState<"instant" | "hourly">("hourly");
  const [savingRedeem, setSavingRedeem] = useState(false);

  // Risk profile settings
  const [minLiquidity, setMinLiquidity] = useState<string>("10000");
  const [slippagePct, setSlippagePct] = useState<string>("3");
  const [savingRisk, setSavingRisk] = useState(false);
  const slippageNum = parseFloat(slippagePct) || 0;
  const liquidityDebounce = useRef<ReturnType<typeof setTimeout> | null>(null);
  const slippageDebounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async () => {
    const [s, dash, autotrade] = await Promise.all([
      api.getSettings(),
      api.getDashboard(),
      api.getAutotrade(),
    ]);
    setSettings(s);
    setTradingMode(dash.trading_mode);
    if (s.auto_redeem != null) setAutoRedeem(s.auto_redeem);
    if (s.redeem_mode) setRedeemMode(s.redeem_mode);
    if (autotrade.min_liquidity != null) setMinLiquidity(String(autotrade.min_liquidity));
  }, [api]);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    return () => {
      if (liquidityDebounce.current) clearTimeout(liquidityDebounce.current);
      if (slippageDebounce.current) clearTimeout(slippageDebounce.current);
    };
  }, []);

  // All three notification toggles bind to the single `notifications_on` flag.
  async function handleNotifToggle(next: boolean) {
    if (!settings) return;
    const optimistic = { ...settings, notifications_on: next };
    setSettings(optimistic);
    try {
      await api.updateSettings({ notifications_on: next });
    } catch (e) {
      setSettings({ ...optimistic, notifications_on: !next });
      console.error("notif toggle failed", e);
    }
  }

  async function handleRedeemToggle(next: boolean) {
    setAutoRedeem(next);
    setSavingRedeem(true);
    try {
      await api.updateTradingSettings({ auto_redeem: next, redeem_mode: redeemMode });
    } catch (e) {
      setAutoRedeem(!next);
      console.error("redeem toggle failed", e);
    } finally {
      setSavingRedeem(false);
    }
  }

  async function handleRedeemModeChange(mode: "instant" | "hourly") {
    setRedeemMode(mode);
    if (autoRedeem) {
      setSavingRedeem(true);
      try {
        await api.updateTradingSettings({ auto_redeem: true, redeem_mode: mode });
      } catch (e) {
        console.error("redeem mode change failed", e);
      } finally {
        setSavingRedeem(false);
      }
    }
  }

  function handleLiquidityChange(val: string) {
    setMinLiquidity(val);
    if (liquidityDebounce.current) clearTimeout(liquidityDebounce.current);
    liquidityDebounce.current = setTimeout(async () => {
      const num = parseFloat(val);
      if (isNaN(num) || num < 0) return;
      setSavingRisk(true);
      try {
        await api.updateTradingSettings({ min_liquidity_usd: num });
      } catch (e) {
        console.error("min_liquidity save failed", e);
      } finally {
        setSavingRisk(false);
      }
    }, 800);
  }

  function handleSlippageChange(val: string) {
    setSlippagePct(val);
    if (slippageDebounce.current) clearTimeout(slippageDebounce.current);
    slippageDebounce.current = setTimeout(async () => {
      const num = parseFloat(val);
      if (isNaN(num) || num < 0 || num > 100) return;
      setSavingRisk(true);
      try {
        await api.updateTradingSettings({ slippage_tolerance_pct: num / 100 });
      } catch (e) {
        console.error("slippage save failed", e);
      } finally {
        setSavingRisk(false);
      }
    }, 800);
  }

  function handleLogout() {
    logout();
    navigate("/auth", { replace: true });
  }

  if (!settings) return (
    <>
      <TopBar />
      <div className="p-4 text-ink-3 text-sm font-mono">Loading…</div>
    </>
  );

  const notifOn = settings.notifications_on;

  return (
    <>
      <TopBar />
      <div className="px-3.5 pt-3.5 pb-6 animate-page-in">

        {/* Desktop page header — hidden on mobile */}
        <DesktopPageHeader
          title={<>CON<span className="text-gold">FIG</span></>}
          subtitle="DISPLAY · NOTIFICATIONS · TRADING · ACCOUNT"
        />

        <div className="md:grid md:grid-cols-2 md:gap-4 md:items-start">
          {/* Left column */}
          <div>
            {/* Display — master Advanced Mode toggle */}
            <SettingsGroup title="Display">
              <SettingsRow
                emphasis
                name={<>⚡ Advanced Mode</>}
                desc="Show technical data, terminal logs, market IDs, and full diagnostics"
                control={
                  <Toggle
                    checked={advanced}
                    onChange={toggleAdvanced}
                    ariaLabel="Toggle advanced mode"
                  />
                }
              />
            </SettingsGroup>

            {/* Notifications */}
            <SettingsGroup title="Notifications">
              <SettingsRow
                name="Trade Opened"
                desc="Alert when a position opens"
                control={<Toggle checked={notifOn} onChange={handleNotifToggle} ariaLabel="Toggle trade-opened alerts" />}
              />
              <SettingsRow
                name="Trade Closed"
                desc="Alert on TP / SL / expiry"
                control={<Toggle checked={notifOn} onChange={handleNotifToggle} ariaLabel="Toggle trade-closed alerts" />}
              />
              <SettingsRow
                name="Daily Report"
                desc="End-of-day P&L summary"
                control={<Toggle checked={notifOn} onChange={handleNotifToggle} ariaLabel="Toggle daily report" />}
              />
            </SettingsGroup>

            {/* Trading — auto redeem */}
            <SettingsGroup title="Trading">
              <SettingsRow
                emphasis
                name="Auto Redeem"
                desc="Automatically redeem winning positions after market resolution"
                control={
                  <Toggle
                    checked={autoRedeem}
                    onChange={handleRedeemToggle}
                    ariaLabel="Toggle auto redeem"
                    disabled={savingRedeem}
                  />
                }
              />
              {autoRedeem && (
                <div className="px-3 pb-3 pt-1 space-y-1.5">
                  <p className="text-[9px] text-ink-4 uppercase tracking-[1.5px] font-mono mb-2">Redeem Mode</p>
                  {(["instant", "hourly"] as const).map((m) => (
                    <label
                      key={m}
                      className="flex items-center gap-2.5 cursor-pointer group"
                    >
                      <input
                        type="radio"
                        name="redeem_mode"
                        value={m}
                        checked={redeemMode === m}
                        onChange={() => void handleRedeemModeChange(m)}
                        className="accent-gold w-3 h-3"
                      />
                      <div>
                        <span className="text-xs font-bold text-ink-1 capitalize">{m}</span>
                        <span className="ml-1.5 text-[10px] text-ink-3">
                          {m === "instant"
                            ? "— redeem as soon as market resolves"
                            : "— batch redeem every hour"}
                        </span>
                      </div>
                    </label>
                  ))}
                </div>
              )}
            </SettingsGroup>
          </div>

          {/* Right column */}
          <div>
            {/* Risk Profile */}
            <SettingsGroup title="Risk Profile">
              <SettingsRow
                name="Min Market Liquidity"
                desc={`Conservative: $25,000 · Balanced: $10,000 · Aggressive: $2,500`}
                control={
                  <div className="flex items-center gap-1.5">
                    <span className="text-ink-3 font-mono text-xs">$</span>
                    <input
                      type="number"
                      min={0}
                      step={500}
                      value={minLiquidity}
                      onChange={(e) => handleLiquidityChange(e.target.value)}
                      className="w-24 bg-surface-2 border border-border-1 rounded px-2 py-1 text-xs font-mono text-ink-1 focus:outline-none focus:border-gold"
                      placeholder="10000"
                    />
                    {savingRisk && <span className="text-ink-4 text-[9px]">saving…</span>}
                  </div>
                }
              />
              <SettingsRow
                name="Slippage Tolerance"
                desc="Warn when your tolerance exceeds 3%"
                control={
                  <div className="flex items-center gap-1.5">
                    <input
                      type="number"
                      min={0}
                      max={100}
                      step={0.5}
                      value={slippagePct}
                      onChange={(e) => handleSlippageChange(e.target.value)}
                      className="w-16 bg-surface-2 border border-border-1 rounded px-2 py-1 text-xs font-mono text-ink-1 focus:outline-none focus:border-gold"
                      placeholder="3"
                    />
                    <span className="text-ink-3 font-mono text-xs">%</span>
                  </div>
                }
              />
              {slippageNum > 3 && (
                <div className="mx-3 mb-3 px-2.5 py-2 rounded text-[10px] font-mono"
                  style={{ background: "rgba(255,200,0,0.08)", border: "1px solid rgba(255,200,0,0.25)", color: "#F5C842" }}>
                  ⚠ High slippage tolerance. You may experience poor execution prices on thin markets.
                </div>
              )}
            </SettingsGroup>

            {/* Account */}
            <SettingsGroup title="Account">
              <SettingsRow
                name="Mode"
                desc="Trading environment"
                control={<ModePill mode={tradingMode} />}
              />
              <SettingsRow
                name="Username"
                desc="Telegram"
                control={`@${user?.firstName ?? "—"}`}
              />
              <AdvancedOnly>
                <SettingsRow
                  name="User ID"
                  desc="Telegram ID"
                  control={user?.userId ?? "—"}
                />
                <SettingsRow
                  name="Risk Profile"
                  desc="Current tier"
                  control={settings.risk_profile.toUpperCase()}
                />
                <SettingsRow
                  name="Activation Guards"
                  desc="Live trading enabled when all guards pass"
                  control={<span className="text-gold">🔒 LOCKED</span>}
                />
              </AdvancedOnly>
            </SettingsGroup>
          </div>
        </div>

        {/* Disconnect */}
        <button
          type="button"
          onClick={handleLogout}
          className="clip-btn font-hud text-[10px] font-bold tracking-[1.5px] uppercase py-3 px-2.5 transition-colors w-full text-red border cursor-pointer mt-2"
          style={{
            background: "rgba(255,45,85,0.08)",
            borderColor: "rgba(255,45,85,0.3)",
          }}
        >
          ⚠ Disconnect Account
        </button>

        <p className="text-ink-4 text-xs text-center mt-6 font-mono tracking-[0.5px]">
          System in paper trading mode. No real capital deployed.
        </p>
      </div>
    </>
  );
}

function ModePill({ mode }: { mode: string }) {
  const live = mode === "live";
  return (
    <span
      className="inline-flex items-center gap-1.5 py-1 pl-2 pr-2.5 font-mono text-[9px] font-bold tracking-[1.5px] clip-card-sm"
      style={
        live
          ? {
              background: "rgba(0,255,156,0.08)",
              border: "1px solid rgba(0,255,156,0.3)",
              color: "var(--grn,#00FF9C)",
            }
          : {
              background: "rgba(245,200,66,0.08)",
              border: "1px solid rgba(245,200,66,0.3)",
              color: "var(--gold,#F5C842)",
            }
      }
    >
      {live ? "LIVE" : "PAPER"}
    </span>
  );
}
