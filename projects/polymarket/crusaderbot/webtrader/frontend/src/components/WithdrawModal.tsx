import { useState } from "react";
import type { WithdrawResponse } from "../lib/api";

type Step = "amount" | "address" | "confirm" | "submitting" | "success" | "error";

const EVM_RE = /^0x[0-9a-fA-F]{40}$/;
const MIN_USDC = 5;

interface Props {
  paperMode: boolean;
  balance: number;
  onClose: () => void;
  onWithdraw: (amount: number, address: string) => Promise<WithdrawResponse>;
  onSuccess?: () => void;
}

export function WithdrawModal({ paperMode, balance, onClose, onWithdraw, onSuccess }: Props) {
  const [step, setStep] = useState<Step>("amount");
  const [amountStr, setAmountStr] = useState("");
  const [address, setAddress] = useState("");
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [result, setResult] = useState<WithdrawResponse | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const amount = parseFloat(amountStr) || 0;

  function handleAmountNext() {
    if (isNaN(amount) || amount < MIN_USDC) {
      setFieldError(`Minimum withdrawal is $${MIN_USDC}.00 USDC`);
      return;
    }
    if (amount > balance) {
      setFieldError(`Insufficient balance (available: $${balance.toFixed(2)})`);
      return;
    }
    setFieldError(null);
    setStep("address");
  }

  function handleAddressNext() {
    const trimmed = address.trim();
    if (!EVM_RE.test(trimmed)) {
      setFieldError("Enter a valid Ethereum/Polygon address (0x + 40 hex chars)");
      return;
    }
    setFieldError(null);
    setAddress(trimmed);
    setStep("confirm");
  }

  async function handleSubmit() {
    setStep("submitting");
    try {
      const resp = await onWithdraw(amount, address.trim());
      setResult(resp);
      setStep("success");
      onSuccess?.();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setSubmitError(msg.replace(/^\d+:\s*/, ""));
      setStep("error");
    }
  }

  const shortAddr = address
    ? `${address.slice(0, 6)}…${address.slice(-4)}`
    : "";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-2"
      style={{ background: "rgba(0,0,0,0.78)" }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
      role="dialog"
      aria-modal="true"
      aria-label="Withdraw USDC"
    >
      <div
        className="w-full max-w-sm bg-surface border border-border-1 clip-card p-5 pb-8 md:pb-5 max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            {(step === "address" || step === "confirm") && (
              <button
                type="button"
                onClick={() => { setFieldError(null); setStep(step === "confirm" ? "address" : "amount"); }}
                className="text-ink-3 hover:text-ink-1 text-[13px] font-mono leading-none"
                aria-label="Back"
              >
                ←
              </button>
            )}
            <p className="font-hud text-[11px] font-bold tracking-[2px] uppercase text-gold">
              {step === "success" ? "Request Submitted" : "Withdraw USDC"}
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
        {(step === "amount" || step === "address" || step === "confirm") && (
          <div className="flex gap-1 mb-4">
            {["amount", "address", "confirm"].map((s, i) => (
              <div
                key={s}
                className="h-[2px] flex-1 rounded-full transition-colors"
                style={{
                  background:
                    ["amount", "address", "confirm"].indexOf(step) >= i
                      ? "rgba(245,200,66,0.8)"
                      : "rgba(255,255,255,0.1)",
                }}
              />
            ))}
          </div>
        )}

        {/* Paper mode warning banner */}
        {paperMode && step !== "success" && step !== "error" && (
          <div
            className="p-2.5 rounded-sm mb-3"
            style={{
              background: "rgba(245,200,66,0.06)",
              border: "1px solid rgba(245,200,66,0.2)",
            }}
          >
            <p className="font-hud text-[9px] font-bold tracking-[1.5px] uppercase text-gold mb-0.5">
              Paper Mode
            </p>
            <p className="text-[9px] font-mono text-ink-3">
              Paper credits — no real USDC will be transferred. Request queued for admin.
            </p>
          </div>
        )}

        {/* ── Step: amount ── */}
        {step === "amount" && (
          <div className="space-y-3">
            <div>
              <label className="block font-hud text-[9px] font-bold tracking-[1.5px] uppercase text-ink-3 mb-1.5">
                Amount (USDC)
              </label>
              <div className="relative">
                <span className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-3 font-mono text-[12px]">$</span>
                <input
                  type="number"
                  min={MIN_USDC}
                  max={balance}
                  step="0.01"
                  value={amountStr}
                  onChange={(e) => { setAmountStr(e.target.value); setFieldError(null); }}
                  onKeyDown={(e) => { if (e.key === "Enter") handleAmountNext(); }}
                  placeholder="0.00"
                  autoFocus
                  className="w-full pl-6 pr-3 py-2.5 bg-transparent border border-border-1 font-mono text-[13px] text-ink-1 rounded-sm focus:outline-none focus:border-gold/50 placeholder-ink-4"
                />
              </div>
              <p className="text-[9px] font-mono text-ink-4 mt-1">
                Min $5.00 · Available ${balance.toFixed(2)}
              </p>
              {fieldError && (
                <p className="text-[9px] font-mono mt-1" style={{ color: "#FF6B6B" }}>
                  {fieldError}
                </p>
              )}
            </div>
            <div className="flex gap-1.5">
              {[25, 50, 100].map((pct) => {
                const v = ((balance * pct) / 100).toFixed(2);
                return (
                  <button
                    key={pct}
                    type="button"
                    onClick={() => { setAmountStr(v); setFieldError(null); }}
                    className="flex-1 py-1.5 font-hud text-[9px] font-bold tracking-[1px] uppercase text-ink-3 border border-border-1 rounded-sm hover:border-gold/40 hover:text-gold transition-colors"
                    style={{ background: "rgba(255,255,255,0.02)" }}
                  >
                    {pct}%
                  </button>
                );
              })}
              <button
                type="button"
                onClick={() => { setAmountStr(balance.toFixed(2)); setFieldError(null); }}
                className="flex-1 py-1.5 font-hud text-[9px] font-bold tracking-[1px] uppercase text-ink-3 border border-border-1 rounded-sm hover:border-gold/40 hover:text-gold transition-colors"
                style={{ background: "rgba(255,255,255,0.02)" }}
              >
                Max
              </button>
            </div>
            <button
              type="button"
              onClick={handleAmountNext}
              className="w-full clip-btn font-hud text-[10px] font-bold tracking-[1.5px] uppercase py-2.5 transition-colors"
              style={{
                background: "rgba(245,200,66,0.1)",
                border: "1px solid rgba(245,200,66,0.35)",
                color: "#F5C842",
              }}
            >
              Continue →
            </button>
          </div>
        )}

        {/* ── Step: address ── */}
        {step === "address" && (
          <div className="space-y-3">
            <div>
              <label className="block font-hud text-[9px] font-bold tracking-[1.5px] uppercase text-ink-3 mb-1.5">
                Destination Address (EVM / Polygon)
              </label>
              <input
                type="text"
                value={address}
                onChange={(e) => { setAddress(e.target.value); setFieldError(null); }}
                onKeyDown={(e) => { if (e.key === "Enter") handleAddressNext(); }}
                placeholder="0x…"
                autoFocus
                spellCheck={false}
                className="w-full px-3 py-2.5 bg-transparent border border-border-1 font-mono text-[11px] text-ink-1 rounded-sm focus:outline-none focus:border-gold/50 placeholder-ink-4"
              />
              <p className="text-[9px] font-mono text-ink-4 mt-1">
                Must be a valid Ethereum-compatible address on Polygon.
              </p>
              {fieldError && (
                <p className="text-[9px] font-mono mt-1" style={{ color: "#FF6B6B" }}>
                  {fieldError}
                </p>
              )}
            </div>
            <button
              type="button"
              onClick={handleAddressNext}
              className="w-full clip-btn font-hud text-[10px] font-bold tracking-[1.5px] uppercase py-2.5 transition-colors"
              style={{
                background: "rgba(245,200,66,0.1)",
                border: "1px solid rgba(245,200,66,0.35)",
                color: "#F5C842",
              }}
            >
              Continue →
            </button>
          </div>
        )}

        {/* ── Step: confirm ── */}
        {step === "confirm" && (
          <div className="space-y-3">
            <div
              className="p-3.5 rounded-sm space-y-2"
              style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}
            >
              <Row label="Amount" value={`$${amount.toFixed(2)} USDC`} highlight />
              <Row label="To" value={shortAddr} />
              <Row label="Status" value="Pending admin approval" />
            </div>
            <p className="text-[9px] font-mono text-ink-4 text-center">
              Withdrawal requests are reviewed before processing.
            </p>
            <button
              type="button"
              onClick={() => void handleSubmit()}
              className="w-full clip-btn font-hud text-[10px] font-bold tracking-[1.5px] uppercase py-2.5 transition-colors"
              style={{
                background: "rgba(245,200,66,0.12)",
                border: "1px solid rgba(245,200,66,0.45)",
                color: "#F5C842",
              }}
            >
              Confirm Withdraw
            </button>
          </div>
        )}

        {/* ── Step: submitting ── */}
        {step === "submitting" && (
          <div className="py-6 text-center">
            <p className="font-hud text-[10px] font-bold tracking-[1.5px] uppercase text-ink-3 animate-pulse">
              Submitting…
            </p>
          </div>
        )}

        {/* ── Step: success ── */}
        {step === "success" && result && (
          <div className="space-y-3">
            <div
              className="p-3.5 rounded-sm space-y-2"
              style={{
                background: "rgba(0,255,156,0.05)",
                border: "1px solid rgba(0,255,156,0.2)",
              }}
            >
              <p className="font-hud text-[10px] font-bold tracking-[1.5px] uppercase text-center mb-2" style={{ color: "#00FF9C" }}>
                Request Submitted
              </p>
              <Row label="Amount" value={`$${result.amount_usdc.toFixed(2)} USDC`} highlight />
              <Row label="Status" value="Pending approval" />
              <Row label="ID" value={result.id.slice(0, 8) + "…"} />
            </div>
            <p className="text-[9px] font-mono text-ink-4 text-center">
              You will be notified via Telegram when the request is processed.
            </p>
            <button
              type="button"
              onClick={onClose}
              className="w-full clip-btn font-hud text-[10px] font-bold tracking-[1.5px] uppercase py-2.5 transition-colors"
              style={{
                background: "rgba(255,255,255,0.04)",
                border: "1px solid rgba(255,255,255,0.1)",
                color: "#888",
              }}
            >
              Close
            </button>
          </div>
        )}

        {/* ── Step: error ── */}
        {step === "error" && (
          <div className="space-y-3">
            <div
              className="p-3.5 rounded-sm"
              style={{
                background: "rgba(255,45,85,0.06)",
                border: "1px solid rgba(255,45,85,0.22)",
              }}
            >
              <p className="font-hud text-[10px] font-bold tracking-[1.5px] uppercase mb-1" style={{ color: "#FF6B6B" }}>
                Request Failed
              </p>
              <p className="text-[9px] font-mono text-ink-3">{submitError}</p>
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => { setSubmitError(null); setStep("confirm"); }}
                className="flex-1 clip-btn font-hud text-[10px] font-bold tracking-[1.5px] uppercase py-2.5 transition-colors"
                style={{
                  background: "rgba(245,200,66,0.08)",
                  border: "1px solid rgba(245,200,66,0.25)",
                  color: "#F5C842",
                }}
              >
                Retry
              </button>
              <button
                type="button"
                onClick={onClose}
                className="flex-1 clip-btn font-hud text-[10px] font-bold tracking-[1.5px] uppercase py-2.5 transition-colors"
                style={{
                  background: "rgba(255,255,255,0.04)",
                  border: "1px solid rgba(255,255,255,0.08)",
                  color: "#888",
                }}
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
      <span
        className={`font-mono text-[11px] ${highlight ? "text-gold" : "text-ink-2"}`}
      >
        {value}
      </span>
    </div>
  );
}
