import { useCallback, useEffect, useMemo, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { makeApi, type TwoFactorSetup, type TwoFactorStatus } from "../lib/api";
import { useAuth } from "../lib/auth";
import { SettingsGroup } from "./SettingsGroup";

// Self-serve TOTP 2FA — closes live_checklist gate 7. The user enrolls here
// without an operator round-trip; the verify call writes the same
// system_settings[2fa_enabled:{user_id}] flag the backend gate already reads.

type Step = "loading" | "off" | "enrolling" | "verifying" | "on" | "disabling";

export function TwoFactorSetupCard({ onChanged }: { onChanged?: () => void }) {
  const { user } = useAuth();
  const api = useMemo(() => makeApi(user?.token ?? null), [user?.token]);
  const [step, setStep] = useState<Step>("loading");
  const [status, setStatus] = useState<TwoFactorStatus | null>(null);
  const [setupData, setSetupData] = useState<TwoFactorSetup | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  const loadStatus = useCallback(async () => {
    try {
      const s = await api.get2faStatus();
      setStatus(s);
      setStep(s.enabled ? "on" : "off");
    } catch {
      setStep("off");
    }
  }, [api]);

  useEffect(() => { void loadStatus(); }, [loadStatus]);

  async function handleStartSetup() {
    setError(null);
    setBusy(true);
    try {
      const data = await api.setup2fa();
      setSetupData(data);
      setCode("");
      setStep("enrolling");
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Setup failed";
      setError(msg.replace(/^\d+:\s*/, ""));
    } finally {
      setBusy(false);
    }
  }

  async function handleVerify() {
    if (code.replace(/\s/g, "").length !== 6) {
      setError("Enter the 6-digit code from your authenticator app");
      return;
    }
    setError(null);
    setStep("verifying");
    try {
      await api.verify2fa(code.replace(/\s/g, ""));
      setSetupData(null);
      setCode("");
      setStatus({ enrolled: true, enabled: true });
      setStep("on");
      onChanged?.();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Verification failed";
      setError(msg.replace(/^\d+:\s*/, ""));
      setStep("enrolling");
    }
  }

  async function handleDisable() {
    if (code.replace(/\s/g, "").length !== 6) {
      setError("Enter the current 6-digit code to confirm");
      return;
    }
    setError(null);
    setStep("disabling");
    try {
      await api.disable2fa(code.replace(/\s/g, ""));
      setStatus({ enrolled: false, enabled: false });
      setCode("");
      setStep("off");
      onChanged?.();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Disable failed";
      setError(msg.replace(/^\d+:\s*/, ""));
      setStep("on");
    }
  }

  function handleCopy(text: string) {
    try {
      void navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch { /* swallow */ }
  }

  return (
    <SettingsGroup title="Two-Factor Authentication">
      <div className="px-3 py-3 space-y-3">
        {step === "loading" && (
          <p className="text-[10px] font-mono text-ink-3">Loading…</p>
        )}

        {/* ── OFF: not yet enrolled ─────────────────────────────────────── */}
        {step === "off" && (
          <>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs font-bold text-ink-1">2FA Status</p>
                <p className="text-[10px] text-ink-3 mt-0.5">
                  Required for live trading. Off — turn on before going live.
                </p>
              </div>
              <span
                className="font-hud text-[9px] font-bold tracking-[1.5px] uppercase px-2 py-0.5 rounded-sm"
                style={{ background: "rgba(245,200,66,0.1)", border: "1px solid rgba(245,200,66,0.3)", color: "#F5C842" }}
              >
                OFF
              </span>
            </div>
            <p className="text-[10px] text-ink-3 leading-relaxed">
              Use any authenticator app — Google Authenticator, Authy, 1Password,
              Microsoft Authenticator. We never see your codes; the app derives
              them locally from a shared secret.
            </p>
            <button
              type="button"
              onClick={() => void handleStartSetup()}
              disabled={busy}
              className="w-full clip-btn font-hud text-[10px] font-bold tracking-[1.5px] uppercase py-2.5 transition-colors disabled:opacity-50"
              style={{ background: "rgba(0,255,156,0.1)", border: "1px solid rgba(0,255,156,0.35)", color: "#00FF9C" }}
            >
              {busy ? "…" : "Set up 2FA →"}
            </button>
            {error && (
              <p className="text-[10px] font-mono" style={{ color: "#FF6B6B" }}>{error}</p>
            )}
          </>
        )}

        {/* ── ENROLLING: show secret + QR + code input ──────────────────── */}
        {(step === "enrolling" || step === "verifying") && setupData && (
          <>
            <div>
              <p className="font-hud text-[9px] font-bold tracking-[1.5px] uppercase text-ink-3 mb-1.5">
                1. Scan the QR with your authenticator app
              </p>
              <div className="flex justify-center py-2">
                <div
                  className="p-2 bg-white rounded-sm"
                  style={{ width: "fit-content" }}
                >
                  <QRCodeSVG value={setupData.otpauth_uri} size={160} level="M" />
                </div>
              </div>
              <p className="text-[10px] text-ink-3 text-center">
                Or enter this secret manually:
              </p>
              <div
                className="mt-1.5 px-2 py-1.5 rounded-sm flex items-center justify-between gap-2"
                style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}
              >
                <code
                  className="text-[11px] font-mono text-ink-1 break-all"
                  style={{ wordBreak: "break-all" }}
                >
                  {setupData.secret}
                </code>
                <button
                  type="button"
                  onClick={() => handleCopy(setupData.secret)}
                  className="font-hud text-[8px] font-bold tracking-[1.5px] uppercase text-gold flex-shrink-0"
                >
                  {copied ? "Copied!" : "Copy"}
                </button>
              </div>
            </div>
            <div>
              <p className="font-hud text-[9px] font-bold tracking-[1.5px] uppercase text-ink-3 mb-1.5">
                2. Enter the 6-digit code your app shows
              </p>
              <input
                type="text"
                inputMode="numeric"
                pattern="[0-9]*"
                maxLength={6}
                value={code}
                onChange={(e) => { setCode(e.target.value.replace(/\D/g, "")); setError(null); }}
                onKeyDown={(e) => { if (e.key === "Enter") void handleVerify(); }}
                placeholder="123 456"
                autoFocus
                spellCheck={false}
                className="w-full px-3 py-2.5 bg-transparent border border-border-1 font-mono text-[14px] text-ink-1 tracking-[3px] text-center rounded-sm focus:outline-none focus:border-gold/50 placeholder-ink-4"
              />
            </div>
            {error && (
              <p className="text-[10px] font-mono" style={{ color: "#FF6B6B" }}>{error}</p>
            )}
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => { setSetupData(null); setCode(""); setError(null); setStep("off"); }}
                className="flex-1 clip-btn font-hud text-[10px] font-bold tracking-[1.5px] uppercase py-2.5 transition-colors"
                style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.1)", color: "#888" }}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => void handleVerify()}
                disabled={step === "verifying" || code.length !== 6}
                className="flex-1 clip-btn font-hud text-[10px] font-bold tracking-[1.5px] uppercase py-2.5 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                style={{ background: "rgba(0,255,156,0.12)", border: "1px solid rgba(0,255,156,0.45)", color: "#00FF9C" }}
              >
                {step === "verifying" ? "…" : "Verify & Enable"}
              </button>
            </div>
          </>
        )}

        {/* ── ON: enabled, allow disable with current code ──────────────── */}
        {(step === "on" || step === "disabling") && status?.enabled && (
          <>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs font-bold text-ink-1">2FA Status</p>
                <p className="text-[10px] text-ink-3 mt-0.5">
                  Enabled. Live trading gate 7 passes.
                </p>
              </div>
              <span
                className="font-hud text-[9px] font-bold tracking-[1.5px] uppercase px-2 py-0.5 rounded-sm"
                style={{ background: "rgba(0,255,156,0.08)", border: "1px solid rgba(0,255,156,0.3)", color: "#00FF9C" }}
              >
                ON
              </span>
            </div>
            <details className="border-t border-border-1 pt-3">
              <summary className="cursor-pointer text-[10px] font-mono text-ink-3 hover:text-ink-1">
                Turn off 2FA
              </summary>
              <div className="mt-2 space-y-2">
                <p className="text-[10px] text-ink-3 leading-relaxed">
                  Enter your current 6-digit code to confirm. Disabling 2FA will
                  block live trading until you re-enable it.
                </p>
                <input
                  type="text"
                  inputMode="numeric"
                  pattern="[0-9]*"
                  maxLength={6}
                  value={code}
                  onChange={(e) => { setCode(e.target.value.replace(/\D/g, "")); setError(null); }}
                  placeholder="6-digit code"
                  spellCheck={false}
                  className="w-full px-3 py-2 bg-transparent border border-border-1 font-mono text-[12px] text-ink-1 tracking-[3px] text-center rounded-sm focus:outline-none focus:border-gold/50 placeholder-ink-4"
                />
                {error && (
                  <p className="text-[10px] font-mono" style={{ color: "#FF6B6B" }}>{error}</p>
                )}
                <button
                  type="button"
                  onClick={() => void handleDisable()}
                  disabled={step === "disabling" || code.length !== 6}
                  className="w-full clip-btn font-hud text-[10px] font-bold tracking-[1.5px] uppercase py-2 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                  style={{ background: "rgba(245,200,66,0.08)", border: "1px solid rgba(245,200,66,0.3)", color: "#F5C842" }}
                >
                  {step === "disabling" ? "…" : "Confirm Disable"}
                </button>
              </div>
            </details>
          </>
        )}
      </div>
    </SettingsGroup>
  );
}
