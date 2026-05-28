import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AdvancedOnly } from "../components/AdvancedGate";
import { DesktopPageHeader } from "../components/DesktopPageHeader";
import { LiveActivationModal } from "../components/LiveActivationModal";
import { NotificationPrefsCard } from "../components/NotificationPrefsCard";
import { SettingsGroup, SettingsRow } from "../components/SettingsGroup";
import { Toggle } from "../components/Toggle";
import { TopBar } from "../components/TopBar";
import { makeApi, type LiveStatus, type UserSettings } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useSSE } from "../lib/sse";
import { useUiMode } from "../lib/uiMode";

export function SettingsPage() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const api = useMemo(() => makeApi(user?.token ?? null), [user?.token]);
  const { advanced, toggle: toggleAdvanced } = useUiMode();
  const [settings, setSettings] = useState<UserSettings | null>(null);
  const [tradingMode, setTradingMode] = useState<string>("paper");

  // Live-trading activation
  const [liveStatus, setLiveStatus] = useState<LiveStatus | null>(null);
  const [showLiveModal, setShowLiveModal] = useState(false);
  const [disablingLive, setDisablingLive] = useState(false);

  // Link email state
  const [showLinkEmail, setShowLinkEmail] = useState(false);
  const [linkEmail, setLinkEmail] = useState("");
  const [linkPassword, setLinkPassword] = useState("");
  const [linkError, setLinkError] = useState<string | null>(null);
  const [linkSuccess, setLinkSuccess] = useState(false);
  const [linkLoading, setLinkLoading] = useState(false);
  const linkFormRef = useRef<HTMLFormElement>(null);

  async function handleLinkEmail(e: React.FormEvent) {
    e.preventDefault();
    setLinkError(null);
    setLinkLoading(true);
    try {
      await api.linkEmail(linkEmail.trim(), linkPassword);
      setLinkSuccess(true);
      setShowLinkEmail(false);
      setLinkEmail("");
      setLinkPassword("");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to link email";
      setLinkError(msg.replace(/^\d+:\s*/, ""));
    } finally {
      setLinkLoading(false);
    }
  }

  // Auto-redeem local state
  const [autoRedeem, setAutoRedeem] = useState(false);
  const [redeemMode, setRedeemMode] = useState<"instant" | "hourly">("hourly");
  const [savingRedeem, setSavingRedeem] = useState(false);

  const load = useCallback(async () => {
    const [s, dash, live] = await Promise.all([
      api.getSettings(),
      api.getDashboard(),
      // Live status is non-critical to the page — never let it block the
      // rest of Settings from rendering.
      api.getLiveStatus().catch(() => null),
    ]);
    setSettings(s);
    setTradingMode(dash.trading_mode);
    setLiveStatus(live);
    if (s.auto_redeem != null) setAutoRedeem(s.auto_redeem);
    if (s.redeem_mode) setRedeemMode(s.redeem_mode);
  }, [api]);

  useEffect(() => { void load(); }, [load]);

  // SSE: reflect settings changes made via Telegram bot without manual refresh.
  useSSE(user?.token ?? null, { settings: load });

  // 30s polling fallback.
  useEffect(() => {
    const id = setInterval(load, 30_000);
    return () => clearInterval(id);
  }, [load]);

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

  async function handleDisableLive() {
    setDisablingLive(true);
    try {
      await api.disableLive();
      await load();
    } catch (e) {
      console.error("disable live failed", e);
    } finally {
      setDisablingLive(false);
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
          {/* Left column — trading safety first */}
          <div>
            {/* Trading — safety-critical settings first */}
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

            {/* Notifications */}
            <NotificationPrefsCard />

            {/* Display — advanced diagnostics last */}
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
          </div>

          {/* Right column */}
          <div>
            {/* Live Trading — per-user opt-in into real-money execution */}
            <SettingsGroup title="Live Trading">
              <div className="px-3 py-3 space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-xs font-bold text-ink-1">Trading mode</p>
                    <p className="text-[10px] text-ink-3 mt-0.5">
                      {tradingMode === "live"
                        ? "Real USDC is at risk on new trades."
                        : "Practice money — no real funds at risk."}
                    </p>
                  </div>
                  <ModePill mode={tradingMode} />
                </div>

                {tradingMode === "live" ? (
                  <>
                    {liveStatus && (
                      <div
                        className="p-2.5 rounded-sm space-y-1.5"
                        style={{ background: "rgba(0,255,156,0.05)", border: "1px solid rgba(0,255,156,0.18)" }}
                      >
                        <InfoRow
                          label="Capital cap"
                          value={`$${liveStatus.live_capital_cap_usdc.toLocaleString(undefined, { minimumFractionDigits: 2 })} USDC`}
                        />
                        <InfoRow
                          label="Open live exposure"
                          value={`$${liveStatus.open_live_exposure_usdc.toLocaleString(undefined, { minimumFractionDigits: 2 })} USDC`}
                        />
                      </div>
                    )}
                    <p className="text-[10px] text-ink-3 leading-relaxed">
                      The cap is the most open live exposure the bot will hold for you. Switching
                      back to paper stops new real-money trades; open live positions resolve as-is.
                    </p>
                    <button
                      type="button"
                      onClick={() => void handleDisableLive()}
                      disabled={disablingLive}
                      className="w-full clip-btn font-hud text-[10px] font-bold tracking-[1.5px] uppercase py-2.5 transition-colors disabled:opacity-50"
                      style={{ background: "rgba(245,200,66,0.08)", border: "1px solid rgba(245,200,66,0.3)", color: "#F5C842" }}
                    >
                      {disablingLive ? "…" : "Switch back to Paper"}
                    </button>
                  </>
                ) : (
                  <>
                    <p className="text-[10px] text-ink-3 leading-relaxed">
                      Switch from practice to real-money trading. You'll set a capital cap (your
                      max live exposure) and type a confirmation phrase. All risk controls stay on.
                    </p>
                    <button
                      type="button"
                      onClick={() => setShowLiveModal(true)}
                      disabled={!liveStatus}
                      className="w-full clip-btn font-hud text-[10px] font-bold tracking-[1.5px] uppercase py-2.5 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                      style={{ background: "rgba(0,255,156,0.1)", border: "1px solid rgba(0,255,156,0.35)", color: "#00FF9C" }}
                    >
                      {liveStatus && !liveStatus.operator_guards_open
                        ? "🔒 Live locked by operator"
                        : "Enable Live Trading →"}
                    </button>
                  </>
                )}
              </div>
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

              {/* Link Email */}
              <div className="pt-2 border-t border-surface-3 mt-2">
                {linkSuccess ? (
                  <p className="text-grn text-[11px] font-mono py-1">✅ Email linked — you can now log in with email + password.</p>
                ) : !showLinkEmail ? (
                  <button
                    type="button"
                    onClick={() => setShowLinkEmail(true)}
                    className="text-[11px] text-gold font-hud tracking-widest uppercase hover:underline"
                  >
                    + Link Email Login
                  </button>
                ) : (
                  <form ref={linkFormRef} onSubmit={(e) => void handleLinkEmail(e)} className="space-y-2 pt-1">
                    <p className="text-ink-3 text-[11px] font-mono mb-2">
                      Add email + password so you can log in without Telegram.
                    </p>
                    <input
                      type="email"
                      value={linkEmail}
                      onChange={(e) => setLinkEmail(e.target.value)}
                      placeholder="you@example.com"
                      required
                      className="w-full bg-surface-2 border border-border-2 rounded px-3 py-1.5 text-[12px] text-ink-1 placeholder:text-ink-4 focus:outline-none focus:border-gold"
                    />
                    <input
                      type="password"
                      value={linkPassword}
                      onChange={(e) => setLinkPassword(e.target.value)}
                      placeholder="Min 8 characters"
                      required
                      minLength={8}
                      className="w-full bg-surface-2 border border-border-2 rounded px-3 py-1.5 text-[12px] text-ink-1 placeholder:text-ink-4 focus:outline-none focus:border-gold"
                    />
                    {linkError && <p className="text-red-400 text-[11px] font-mono">{linkError}</p>}
                    <div className="flex gap-2">
                      <button
                        type="submit"
                        disabled={linkLoading}
                        className="flex-1 py-1.5 bg-gold text-black font-hud text-[10px] tracking-widest uppercase rounded hover:bg-gold/90 disabled:opacity-50"
                      >
                        {linkLoading ? "…" : "Link Email"}
                      </button>
                      <button
                        type="button"
                        onClick={() => { setShowLinkEmail(false); setLinkError(null); }}
                        className="px-3 py-1.5 border border-surface-3 text-ink-3 font-hud text-[10px] tracking-widest uppercase rounded hover:border-ink-3"
                      >
                        Cancel
                      </button>
                    </div>
                  </form>
                )}
              </div>
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
          {tradingMode === "live"
            ? "Live mode — real capital deployed. Trade responsibly."
            : "System in paper trading mode. No real capital deployed."}
        </p>
      </div>

      {showLiveModal && liveStatus && (
        <LiveActivationModal
          status={liveStatus}
          onClose={() => setShowLiveModal(false)}
          onEnable={(capValue, confirmPhrase) => api.enableLive(capValue, confirmPhrase)}
          onSuccess={() => { void load(); }}
        />
      )}
    </>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between items-center">
      <span className="font-hud text-[9px] font-bold tracking-[1.5px] uppercase text-ink-3">{label}</span>
      <span className="font-mono text-[11px] text-ink-2">{value}</span>
    </div>
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
