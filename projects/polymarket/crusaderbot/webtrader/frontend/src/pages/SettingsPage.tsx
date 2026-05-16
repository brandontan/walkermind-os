import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { makeApi, type UserSettings } from "../lib/api";
import { useAuth } from "../lib/auth";

interface ToggleRowProps {
  label: string;
  on: boolean;
  onToggle: () => void;
}

function ToggleRow({ label, on, onToggle }: ToggleRowProps) {
  return (
    <div className="flex items-center justify-between px-4 py-3.5">
      <p className="text-primary text-sm">{label}</p>
      <button
        onClick={onToggle}
        className="relative shrink-0 transition-colors"
        style={{ width: 44, height: 24 }}
        aria-pressed={on}
      >
        <span
          className="block rounded-full transition-colors"
          style={{
            width: 44,
            height: 24,
            background: on ? "#F5C842" : "#1A2332",
          }}
        />
        <span
          className="absolute top-0.5 rounded-full bg-white transition-transform"
          style={{
            width: 20,
            height: 20,
            left: 2,
            transform: on ? "translateX(20px)" : "translateX(0)",
          }}
        />
      </button>
    </div>
  );
}

export function SettingsPage() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const api = makeApi(user?.token ?? null);
  const [settings, setSettings] = useState<UserSettings | null>(null);

  useEffect(() => {
    api.getSettings().then(setSettings).catch(console.error);
  }, [user?.token]); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleNotifToggle() {
    if (!settings) return;
    const updated = { ...settings, notifications_on: !settings.notifications_on };
    setSettings(updated);
    await api.updateSettings({ notifications_on: updated.notifications_on });
  }

  function handleLogout() {
    logout();
    navigate("/auth", { replace: true });
  }

  if (!settings) return <div className="p-4 text-muted text-sm">Loading…</div>;

  const notifOn = settings.notifications_on;

  return (
    <div className="pb-28 px-4 animate-page-in">
      <div className="pt-6 pb-4">
        <h1 className="text-xl font-bold text-primary">Settings</h1>
      </div>

      {/* Notifications group */}
      <p className="text-muted text-xs uppercase tracking-wide mb-2 px-1">Notifications</p>
      <div className="bg-card border border-border rounded-2xl divide-y divide-border mb-5">
        <ToggleRow label="Trade Opened"     on={notifOn} onToggle={handleNotifToggle} />
        <ToggleRow label="Trade Closed"     on={notifOn} onToggle={handleNotifToggle} />
        <ToggleRow label="Daily Report"     on={notifOn} onToggle={handleNotifToggle} />
        <ToggleRow label="Kill Switch Alert" on={notifOn} onToggle={handleNotifToggle} />
      </div>

      {/* Account group */}
      <p className="text-muted text-xs uppercase tracking-wide mb-2 px-1">Account</p>
      <div className="bg-card border border-border rounded-2xl divide-y divide-border mb-5">
        <div className="flex items-center justify-between px-4 py-3.5">
          <p className="text-primary text-sm">Mode</p>
          <span className="px-2 py-0.5 rounded-full border border-gold/25 bg-gold/10 text-gold text-xs font-medium">
            PAPER
          </span>
        </div>
        <div className="flex items-center justify-between px-4 py-3.5">
          <p className="text-primary text-sm">Username</p>
          <p className="text-muted text-sm">{user?.firstName}</p>
        </div>
        <div className="flex items-center justify-between px-4 py-3.5">
          <p className="text-primary text-sm">Tier</p>
          <p className="text-muted text-sm capitalize">{settings.risk_profile}</p>
        </div>
      </div>

      {/* Disconnect */}
      <button
        onClick={handleLogout}
        className="w-full py-3 rounded-xl border border-red/30 text-red text-sm font-semibold hover:bg-red/10 active:scale-95 transition-all"
      >
        Disconnect
      </button>

      <p className="text-muted/40 text-xs text-center mt-6">
        System in paper trading mode. No real capital deployed.
      </p>
    </div>
  );
}
