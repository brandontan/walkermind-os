import { useCallback, useEffect, useMemo, useState } from "react";
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

  const load = useCallback(async () => {
    const [s, dash] = await Promise.all([
      api.getSettings(),
      api.getDashboard(),
    ]);
    setSettings(s);
    setTradingMode(dash.trading_mode);
    if (s.auto_redeem != null) setAutoRedeem(s.auto_redeem);
    if (s.redeem_mode) setRedeemMode(s.redeem_mode);
  }, [api]);

  useEffect(() => { void load(); }, [load]);

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
