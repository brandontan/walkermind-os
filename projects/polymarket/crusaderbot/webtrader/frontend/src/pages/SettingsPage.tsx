import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AdvancedOnly } from "../components/AdvancedGate";
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

  const load = useCallback(async () => {
    const [s, dash] = await Promise.all([api.getSettings(), api.getDashboard()]);
    setSettings(s);
    setTradingMode(dash.trading_mode);
  }, [api]);

  useEffect(() => { void load(); }, [load]);

  // All three notification toggles bind to the single `notifications_on`
  // backend flag. Granular per-event preferences need a backend schema
  // extension — tracked as follow-up in the forge report.
  async function handleNotifToggle(next: boolean) {
    if (!settings) return;
    const optimistic = { ...settings, notifications_on: next };
    setSettings(optimistic);
    try {
      await api.updateSettings({ notifications_on: next });
    } catch (e) {
      // Roll back optimistic update on failure.
      setSettings({ ...optimistic, notifications_on: !next });
      console.error("notif toggle failed", e);
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

        {/* Display group — master Advanced Mode toggle */}
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
