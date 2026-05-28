import { useState } from "react";
import {
  LIVE_CAP_MAX_USDC,
  LIVE_CAP_MIN_USDC,
  LIVE_ENABLE_CONFIRM_PHRASE,
  type LiveEnableResponse,
  type LiveStatus,
} from "../lib/api";

type Step = "preview" | "cap" | "confirm" | "submitting" | "success" | "error";

interface Props {
  status: LiveStatus;
  onClose: () => void;
  onEnable: (cap: number, phrase: string) => Promise<LiveEnableResponse>;
  onSuccess?: () => void;
}

// Human-friendly labels for the raw gate keys the backend returns.
const GATE_LABELS: Record<string, string> = {
  funded: "Wallet funded with real USDC",
  wallet: "Trading wallet ready",
  risk_profile: "Risk profile selected",
  preset: "A strategy preset is active",
  tos: "Terms of Service accepted",
  no_kill: "Kill switch is off",
  guards: "Operator system guards open",
};

function prettyGate(g: string): string {
  return GATE_LABELS[g] ?? g.replace(/_/g, " ");
}

export function LiveActivationModal({ status, onClose, onEnable, onSuccess }: Props) {
  const ready = status.operator_guards_open && status.checklist_passed;
  const [step, setStep] = useState<Step>("preview");
  const [capStr, setCapStr] = useState(
    status.live_capital_cap_usdc > 0 ? String(status.live_capital_cap_usdc) : ""
  );
  const [phrase, setPhrase] = useState("");
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [result, setResult] = useState<LiveEnableResponse | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const cap = parseFloat(capStr) || 0;
  const phraseOk = phrase === LIVE_ENABLE_CONFIRM_PHRASE;

  function handleCapNext() {
    if (isNaN(cap) || cap <= LIVE_CAP_MIN_USDC) {
      setFieldError("Enter a cap greater than 0 USDC");
      return;
    }
    if (cap > LIVE_CAP_MAX_USDC) {
      setFieldError(`Maximum cap is $${LIVE_CAP_MAX_USDC.toLocaleString()} USDC`);
      return;
    }
    setFieldError(null);
    setStep("confirm");
  }

  async function handleSubmit() {
    if (!phraseOk) return;
    setStep("submitting");
    try {
      const resp = await onEnable(cap, phrase);
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
            {(step === "cap" || step === "confirm") && (
              <button
                type="button"
                onClick={() => { setFieldError(null); setStep(step === "confirm" ? "cap" : "preview"); }}
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
        {(step === "preview" || step === "cap" || step === "confirm") && (
          <div className="flex gap-1 mb-4">
            {["preview", "cap", "confirm"].map((s, i) => (
              <div
                key={s}
                className="h-[2px] flex-1 rounded-full transition-colors"
                style={{
                  background:
                    ["preview", "cap", "confirm"].indexOf(step) >= i
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
              Live trading uses <span className="text-ink-1 font-bold">real USDC</span> from your
              wallet. Trades can win or lose real money. Paper mode is practice with no risk —
              live mode is not.
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
              onClick={() => setStep("cap")}
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

        {/* ── Step: capital cap ── */}
        {step === "cap" && (
          <div className="space-y-3">
            <div>
              <label className="block font-hud text-[9px] font-bold tracking-[1.5px] uppercase text-ink-3 mb-1.5">
                Capital cap (USDC)
              </label>
              <div className="relative">
                <span className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-3 font-mono text-[12px]">$</span>
                <input
                  type="number"
                  min={1}
                  max={LIVE_CAP_MAX_USDC}
                  step="1"
                  value={capStr}
                  onChange={(e) => { setCapStr(e.target.value); setFieldError(null); }}
                  onKeyDown={(e) => { if (e.key === "Enter") handleCapNext(); }}
                  placeholder="500"
                  autoFocus
                  className="w-full pl-6 pr-3 py-2.5 bg-transparent border border-border-1 font-mono text-[13px] text-ink-1 rounded-sm focus:outline-none focus:border-gold/50 placeholder-ink-4"
                />
              </div>
              <p className="text-[10px] font-mono text-ink-3 mt-1.5 leading-relaxed">
                The most USDC of <span className="text-ink-1">open live positions</span> the bot may
                hold for you at once. It's your hard ceiling on live exposure — every live trade is
                checked against it. Range: $1 – ${LIVE_CAP_MAX_USDC.toLocaleString()}.
              </p>
              {fieldError && (
                <p className="text-[9px] font-mono mt-1" style={{ color: "#FF6B6B" }}>{fieldError}</p>
              )}
            </div>
            <div className="flex gap-1.5">
              {[100, 250, 500, 1000].map((v) => (
                <button
                  key={v}
                  type="button"
                  onClick={() => { setCapStr(String(v)); setFieldError(null); }}
                  className="flex-1 py-1.5 font-hud text-[9px] font-bold tracking-[1px] uppercase text-ink-3 border border-border-1 rounded-sm hover:border-gold/40 hover:text-gold transition-colors"
                  style={{ background: "rgba(255,255,255,0.02)" }}
                >
                  ${v}
                </button>
              ))}
            </div>
            <button
              type="button"
              onClick={handleCapNext}
              className="w-full clip-btn font-hud text-[10px] font-bold tracking-[1.5px] uppercase py-2.5 transition-colors"
              style={{ background: "rgba(0,255,156,0.1)", border: "1px solid rgba(0,255,156,0.35)", color: "#00FF9C" }}
            >
              Continue →
            </button>
          </div>
        )}

        {/* ── Step: typed confirm ── */}
        {step === "confirm" && (
          <div className="space-y-3">
            <div
              className="p-3.5 rounded-sm space-y-2"
              style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}
            >
              <Row label="Mode" value="LIVE (real money)" highlight />
              <Row label="Capital cap" value={`$${cap.toLocaleString(undefined, { minimumFractionDigits: 2 })} USDC`} highlight />
              <Row label="Safety gates" value="All stay active" />
            </div>
            <p className="text-[10px] font-mono text-ink-3 leading-relaxed">
              Risk controls remain on every trade: Kelly 0.25, position ≤10% of capital, daily loss
              limit, drawdown halt, and the kill switch. To confirm, type the phrase exactly:
            </p>
            <p className="text-[11px] font-mono text-gold text-center select-all py-1">
              {LIVE_ENABLE_CONFIRM_PHRASE}
            </p>
            <input
              type="text"
              value={phrase}
              onChange={(e) => setPhrase(e.target.value)}
              placeholder="Type the phrase above"
              autoFocus
              spellCheck={false}
              autoCapitalize="characters"
              className="w-full px-3 py-2.5 bg-transparent border border-border-1 font-mono text-[11px] text-ink-1 rounded-sm focus:outline-none focus:border-gold/50 placeholder-ink-4"
            />
            <button
              type="button"
              disabled={!phraseOk}
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
              <Row label="Capital cap" value={`$${result.live_capital_cap_usdc.toLocaleString(undefined, { minimumFractionDigits: 2 })} USDC`} highlight />
            </div>
            <p className="text-[10px] font-mono text-ink-4 text-center leading-relaxed">
              New trades now use real USDC, capped at your limit. You can switch back to paper
              anytime from Settings.
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
                onClick={() => { setSubmitError(null); setStep("confirm"); }}
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
