import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { makeApi, type UserSettings } from "../lib/api";
import { useAuth } from "../lib/auth";

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

  return (
    <div className="pb-24 px-4">
      <div className="pt-6 pb-4">
        <h1 className="text-xl font-bold text-primary">Settings</h1>
      </div>

      <div className="bg-card border border-border rounded-xl divide-y divide-border mb-4">
        {/* Notifications */}
        <div className="flex items-center justify-between p-4">
          <div>
            <p className="text-primary text-sm font-medium">Notifications</p>
            <p className="text-muted text-xs">Trade alerts and daily reports</p>
          </div>
          <button
            onClick={handleNotifToggle}
            className={`w-12 h-6 rounded-full transition-colors ${settings.notifications_on ? "bg-amber" : "bg-border"}`}
          >
            <span className={`block w-5 h-5 rounded-full bg-white transition-transform mx-0.5 ${settings.notifications_on ? "translate-x-6" : "translate-x-0"}`} />
          </button>
        </div>

        {/* Account */}
        <div className="p-4">
          <p className="text-muted text-xs uppercase tracking-wide mb-2">Account</p>
          <p className="text-primary text-sm">{user?.firstName}</p>
          <p className="text-muted text-xs mt-0.5">User ID: {user?.userId.slice(0, 8)}…</p>
        </div>
      </div>

      {/* Logout */}
      <button
        onClick={handleLogout}
        className="w-full py-3 rounded-xl border border-red/30 text-red text-sm font-medium hover:bg-red/10 transition-colors"
      >
        Disconnect
      </button>

      <p className="text-muted/40 text-xs text-center mt-6">
        System in paper trading mode. No real capital deployed.
      </p>
    </div>
  );
}
