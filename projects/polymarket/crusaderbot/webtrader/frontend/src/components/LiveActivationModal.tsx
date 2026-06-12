import { useState } from "react";
import {
  LIVE_ENABLE_CONSENT_VERSION,
  type LiveEnableResponse,
  type LiveStatus,
} from "../lib/api";

type Step = "preview" | "consent" | "submitting" | "success" | "error";

interface Props {
  status: LiveStatus;
  onClose: () => void;
  onEnable: (consentAccepted: boolean, consentVersion?: string) => Promise<LiveEnableResponse>;
  onSuccess?: () => void;
}

// Human-friendly labels for the raw gate keys the backend returns in
// `failed_gates` — keys MUST match domain/activation/live_checklist.py
// GATE_ORDER exactly (the first three are operator env guards; they only
// appear if guards are open but the checklist still reports them failed).
// NOTE: there is deliberately NO deposit gate — users switch to live first
// and deposit after (the bot stays stopped and zero-fund live trades are
// rejected by the risk gate).
const GATE_LABELS: Record<string, string> = {
  EXECUTION_PATH_VALIDATED: "Operator: execution path validated",
  CAPITAL_MODE_CONFIRMED: "Operator: capital mode confirmed",
  ENABLE_LIVE_TRADING: "Operator: live trading switched on",
  strategy_configured: "A strategy preset is active",
  risk_profile_configured: "Risk profile selected",
  two_factor_setup_complete: "Two-factor authentication enabled (Settings → 2FA)",
  operator_allowlist_approved: "Live access approved by an admin",
};

function prettyGate(g: string): string {
  return GATE_LABELS[g] ?? g.replace(/_/g, " ");
}

function fmtUsd(v: number): string {
  return `$${v.toLocaleString(undefined, { minimumFractionDigits: 2 })}`;
}

export function LiveActivationModal({ status, onClose, onEnable, onSuccess }: Props) {
  const ready = status.operator_guards_open && status.checklist_passed;
  const [step, setStep] = useState<Step>("preview");
  const [consentAccepted, setConsentAccepted] = useState(false);
  const [result, setResult] = useState<LiveEnableResponse | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  async function handleSubmit() {
    if (!consentAccepted) return;
    setStep("submitting");
    try {
      const resp = await onEnable(true, LIVE_ENABLE_CONSENT_VERSION);
      setResult(resp);
      setStep("success");
      onSuccess?.();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setSubmitError(msg.replace(/^\d+:\s*/, ""));
      setStep("error");
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-2"
      style={{ background: "rgba(0,0,0,0.78)" }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
      role="dialog"
      aria-modal="true"
      aria-label="Enable live trading"
    >
      <div
        className="w-full max-w-sm bg-surface border border-border-1 clip-card p-5 pb-8 md:pb-5 max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            {step === "consent" && (
              <button
                type="button"
                onClick={() => setStep("preview")}
                className="text-ink-3 hover:text-ink-1 text-[13px] font-mono leading-none"
                aria-label="Back"
              >
                ←
              </button>
            )}
            <p className="font-hud text-[11px] font-bold tracking-[2px] uppercase" style={{ color: "#00FF9C" }}>
              {step === "success" ? "Live Trading On" : "Enable Live Trading"}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-ink-3 hover:text-ink-1 text-[20px] leading-none p-1 ml-2 flex-shrink-0"
            aria-label="Close"
          >
            ×
          </button>
        </div>

        {/* Step indicator */}
        {(step === "preview" || step === "consent") && (
          <div className="flex gap-1 mb-4">
            {["preview", "consent"].map((s, i) => (
              <div
                key={s}
                className="h-[2px] flex-1 rounded-full transition-colors"
                style={{
                  background:
                    ["preview", "consent"].indexOf(step) >= i
                      ? "rgba(0,255,156,0.8)"
                      : "rgba(255,255,255,0.1)",
                }}
              />
            ))}
          </div>
        )}

        {/* ── Step: preview / readiness ── */}
        {step === "preview" && (
          <div className="space-y-3">
            <p className="text-[11px] font-mono text-ink-2 leading-relaxed">
              Live trading uses <span className="text-ink-1 font-bold">real USDC</span> you
              deposit. No amount to enter — your real deposited balance is the bot's live
              bankroll and its hard exposure ceiling. You can switch now and deposit after.
            </p>
            <div
              className="p-3 rounded-sm space-y-2"
              style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}
            >
              <CheckRow ok={status.operator_guards_open} label="System unlocked for live (operator)" />
              <CheckRow ok={status.checklist_passed} label="Your account passes all readiness checks" />
            </div>

            {!ready && (
              <div
                className="p-3 rounded-sm"
                style={{ background: "rgba(245,200,66,0.06)", border: "1px solid rgba(245,200,66,0.2)" }}
              >
                <p className="font-hud text-[9px] font-bold tracking-[1.5px] uppercase text-gold mb-1">
                  Not ready yet
                </p>
                {!status.operator_guards_open ? (
                  <p className="text-[10px] font-mono text-ink-3">
                    The operator hasn't switched the system to live yet. You can't go live until that's done.
                  </p>
                ) : (
                  <ul className="text-[10px] font-mono text-ink-3 space-y-0.5 list-disc pl-3.5">
                    {status.failed_gates.map((g) => (
                      <li key={g}>{prettyGate(g)}</li>
                    ))}
                  </ul>
                )}
              </div>
            )}

            <button
              type="button"
              disabled={!ready}
              onClick={() => setStep("consent")}
              className="w-full clip-btn font-hud text-[10px] font-bold tracking-[1.5px] uppercase py-2.5 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              style={{
                background: "rgba(0,255,156,0.1)",
                border: "1px solid rgba(0,255,156,0.35)",
                color: "#00FF9C",
              }}
            >
              {ready ? "Continue →" : "Locked"}
            </button>
          </div>
        )}

        {/* ── Step: Terms/risk consent ── */}
        {step === "consent" && (
          <div className="space-y-3">
            <div
              className="p-3.5 rounded-sm space-y-2"
              style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}
            >
              <Row label="Mode" value="LIVE (real money)" highlight />
              <Row label="Live balance" value={`${fmtUsd(status.live_balance_usdc)} USDC`} highlight />
              <Row label="Exposure ceiling" value="Your deposited balance" />
              <Row label="On switch" value="Bot auto-stops" />
              <Row label="Safety gates" value="All stay active" />
            </div>
            <p className="text-[10px] font-mono text-ink-3 leading-relaxed">
              The bot stops the moment you switch — deposit USDC.e, then turn Auto-Trade back on
              when you're ready. With $0 deposited, no live trade can open. Risk controls remain
              on every trade: Kelly 0.25, position ≤10%, daily loss limit, drawdown halt, kill
              switch. 2FA is optional and recommended for account and withdrawal protection; it is
              not required to switch LIVE.
            </p>
            <label
              className="flex gap-3 p-3 rounded-sm cursor-pointer transition-colors"
              style={{ background: consentAccepted ? "rgba(0,255,156,0.08)" : "rgba(255,255,255,0.03)", border: consentAccepted ? "1px solid rgba(0,255,156,0.35)" : "1px solid rgba(255,255,255,0.08)" }}
            >
              <input
                type="checkbox"
                checked={consentAccepted}
                onChange={(e) => setConsentAccepted(e.target.checked)}
                className="mt-0.5 h-4 w-4 accent-[#00FF9C] flex-shrink-0"
                aria-label="Accept live trading terms and risk acknowledgement"
              />
              <span className="text-[10px] font-mono text-ink-2 leading-relaxed">
                I accept the <a href="/legal/terms" target="_blank" rel="noreferrer" className="text-gold underline underline-offset-2">Terms of Service</a> and understand LIVE trading uses real USDC, can lose money, does not start Auto-Trade by itself, and remains blocked from live Auto-Trade until my confirmed available live USDC.e is at least $5.
              </span>
            </label>
            <p className="text-[9px] font-mono text-ink-4 leading-relaxed">
              Consent version: {LIVE_ENABLE_CONSENT_VERSION}. This acknowledgement is recorded with your LIVE enable audit event.
            </p>
            <button
              type="button"
              disabled={!consentAccepted}
              onClick={() => void handleSubmit()}
              className="w-full clip-btn font-hud text-[10px] font-bold tracking-[1.5px] uppercase py-2.5 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              style={{ background: "rgba(0,255,156,0.12)", border: "1px solid rgba(0,255,156,0.45)", color: "#00FF9C" }}
            >
              Enable Live Trading
            </button>
          </div>
        )}

        {/* ── Step: submitting ── */}
        {step === "submitting" && (
          <div className="py-6 text-center">
            <p className="font-hud text-[10px] font-bold tracking-[1.5px] uppercase text-ink-3 animate-pulse">
              Enabling…
            </p>
          </div>
        )}

        {/* ── Step: success ── */}
        {step === "success" && result && (
          <div className="space-y-3">
            <div
              className="p-3.5 rounded-sm space-y-2"
              style={{ background: "rgba(0,255,156,0.05)", border: "1px solid rgba(0,255,156,0.2)" }}
            >
              <p className="font-hud text-[10px] font-bold tracking-[1.5px] uppercase text-center mb-2" style={{ color: "#00FF9C" }}>
                Live Trading Enabled
              </p>
              <Row label="Mode" value="LIVE" highlight />
              <Row label="Live balance" value={`${fmtUsd(result.live_balance_usdc)} USDC`} highlight />
              <Row label="Bot" value="STOPPED — re-arm when funded" />
            </div>
            <p className="text-[10px] font-mono text-ink-4 text-center leading-relaxed">
              Deposit USDC.e to your wallet address, then turn Auto-Trade on to start. New live
              trades use only your real deposited balance. Switch back to paper anytime from
              Settings.
            </p>
            <button
              type="button"
              onClick={onClose}
              className="w-full clip-btn font-hud text-[10px] font-bold tracking-[1.5px] uppercase py-2.5 transition-colors"
              style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.1)", color: "#888" }}
            >
              Done
            </button>
          </div>
        )}

        {/* ── Step: error ── */}
        {step === "error" && (
          <div className="space-y-3">
            <div
              className="p-3.5 rounded-sm"
              style={{ background: "rgba(255,45,85,0.06)", border: "1px solid rgba(255,45,85,0.22)" }}
            >
              <p className="font-hud text-[10px] font-bold tracking-[1.5px] uppercase mb-1" style={{ color: "#FF6B6B" }}>
                Could Not Enable
              </p>
              <p className="text-[9px] font-mono text-ink-3 break-words">{submitError}</p>
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => { setSubmitError(null); setStep("consent"); }}
                className="flex-1 clip-btn font-hud text-[10px] font-bold tracking-[1.5px] uppercase py-2.5 transition-colors"
                style={{ background: "rgba(0,255,156,0.08)", border: "1px solid rgba(0,255,156,0.25)", color: "#00FF9C" }}
              >
                Retry
              </button>
              <button
                type="button"
                onClick={onClose}
                className="flex-1 clip-btn font-hud text-[10px] font-bold tracking-[1.5px] uppercase py-2.5 transition-colors"
                style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)", color: "#888" }}
              >
                Close
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Row({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className="flex justify-between items-center">
      <span className="font-hud text-[9px] font-bold tracking-[1.5px] uppercase text-ink-3">{label}</span>
      <span className={`font-mono text-[11px] ${highlight ? "text-gold" : "text-ink-2"}`}>{value}</span>
    </div>
  );
}

function CheckRow({ ok, label }: { ok: boolean; label: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className="font-mono text-[11px]" style={{ color: ok ? "#00FF9C" : "#FF6B6B" }}>
        {ok ? "✓" : "✕"}
      </span>
      <span className="font-mono text-[10px] text-ink-2">{label}</span>
    </div>
  );
}
