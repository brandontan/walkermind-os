import { useEffect, useMemo, useRef, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import type { DepositOption } from "../lib/api";

interface Props {
  address: string;
  depositOptions?: DepositOption[];
  paperMode: boolean;
  balance?: number;
  onClose: () => void;
}

function legacyOption(address: string): DepositOption {
  return {
    id: "polygon-usdc-e",
    token_symbol: "USDC.e",
    token_label: "USDC.e (bridged)",
    token_contract: null,
    network: "Polygon",
    chain_id: 137,
    display_label: "USDC.e on Polygon",
    decimals: 6,
    min_deposit: 50,
    backend_supported: true,
    watcher_supported: true,
    bridge_custody_supported: true,
    enabled: true,
    unavailable_reason: null,
    deposit_address: address || null,
  };
}

export function DepositModal({ address, depositOptions, paperMode, balance, onClose }: Props) {
  const [copied, setCopied] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const copyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const options = useMemo(() => {
    const normalized = depositOptions && depositOptions.length > 0
      ? depositOptions
      : [legacyOption(address)];
    return normalized.map((option) => ({
      ...option,
      deposit_address: option.deposit_address ?? (option.enabled ? address : null),
    }));
  }, [address, depositOptions]);

  const firstEnabled = options.find((option) => option.enabled);
  const [selectedId, setSelectedId] = useState(firstEnabled?.id ?? options[0]?.id ?? "");

  useEffect(() => {
    if (!options.some((option) => option.id === selectedId)) {
      setSelectedId(firstEnabled?.id ?? options[0]?.id ?? "");
    }
  }, [firstEnabled?.id, options, selectedId]);

  useEffect(() => {
    return () => {
      if (copyTimerRef.current !== null) clearTimeout(copyTimerRef.current);
    };
  }, []);

  const selected = options.find((option) => option.id === selectedId) ?? firstEnabled ?? options[0];
  const selectedAddress = selected?.enabled ? (selected.deposit_address ?? address) : "";
  const hasAddress = Boolean(selectedAddress);
  const selectorDisabled = !selected?.enabled;
  const minDeposit = selected?.min_deposit ? `$${selected.min_deposit.toFixed(0)}` : "Not published";

  const copyAddress = async () => {
    if (!selectedAddress) return;
    try {
      const instruction = `Deposit ${selected.token_label} on ${selected.network} to ${selectedAddress}`;
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(instruction);
      } else {
        const ta = document.createElement("textarea");
        ta.value = instruction;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        // eslint-disable-next-line deprecation/deprecation
        document.execCommand("copy");
        document.body.removeChild(ta);
      }
      setCopied(true);
      if (copyTimerRef.current !== null) clearTimeout(copyTimerRef.current);
      copyTimerRef.current = setTimeout(() => setCopied(false), 1500);
    } catch {}
  };

  return (
    <>
      {/* Modal backdrop */}
      <div
        className="fixed inset-0 z-50 flex items-center justify-center px-2"
        style={{ background: "rgba(0,0,0,0.78)" }}
        onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
        role="dialog"
        aria-modal="true"
        aria-label="Deposit selector"
      >
        <div
          className="w-full max-w-sm bg-surface border border-border-1 clip-card p-5 pb-8 md:pb-5 max-h-[90vh] overflow-y-auto"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <div className="flex items-start justify-between mb-4">
            <div>
              <p className="font-hud text-[11px] font-bold tracking-[2px] uppercase text-gold">
                {paperMode ? "Paper Wallet Address" : "Deposit Funds"}
              </p>
              <p className="text-[9px] font-mono text-ink-3 mt-0.5">
                {paperMode ? "Paper Mode — no real funds at risk" : "Choose token + network"}
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

          <div className="mb-4 space-y-2" aria-label="Deposit token and network options">
            {options.map((option) => {
              const active = option.id === selected?.id;
              return (
                <button
                  type="button"
                  key={option.id}
                  disabled={!option.enabled}
                  onClick={() => setSelectedId(option.id)}
                  className={`w-full text-left rounded-sm border p-2.5 transition-colors ${
                    active ? "border-gold" : "border-border-1"
                  } ${option.enabled ? "hover:border-gold/80" : "opacity-55 cursor-not-allowed"}`}
                  style={{ background: active ? "rgba(245,200,66,0.08)" : "rgba(255,255,255,0.03)" }}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-hud text-[10px] font-bold tracking-[1px] uppercase text-ink-1">
                      {option.display_label}
                    </span>
                    <span className={`font-mono text-[8px] ${option.enabled ? "text-grn" : "text-ink-4"}`}>
                      {option.enabled ? "SUPPORTED" : "UNAVAILABLE"}
                    </span>
                  </div>
                  <div className="mt-1 font-mono text-[8px] text-ink-4 leading-relaxed">
                    Token: {option.token_symbol} · Network: {option.network} · Chain ID: {option.chain_id}
                  </div>
                  {!option.enabled && option.unavailable_reason && (
                    <div className="mt-1 font-mono text-[8px] text-red leading-relaxed">
                      {option.unavailable_reason}
                    </div>
                  )}
                </button>
              );
            })}
          </div>

          {!selected || !hasAddress || selectorDisabled ? (
            <div className="py-8 text-center space-y-1.5">
              <p className="text-[10px] font-mono text-ink-3">
                {selectorDisabled ? "This token/network is not deposit-enabled." : "No deposit address available."}
              </p>
              <p className="text-[9px] font-mono text-ink-4">
                {selectorDisabled
                  ? "Unsupported assets cannot produce QR codes or deposit instructions."
                  : "Set up your wallet via the Telegram bot."}
              </p>
            </div>
          ) : (
            <>
              {/* QR Code */}
              <div className="flex justify-center mb-1">
                <button
                  type="button"
                  onClick={() => setFullscreen(true)}
                  className="p-3 bg-white rounded-sm cursor-pointer hover:opacity-90 transition-opacity"
                  aria-label={`Tap to enlarge ${selected.display_label} QR code`}
                  title="Tap to enlarge"
                >
                  <QRCodeSVG
                    value={selectedAddress}
                    size={156}
                    level="M"
                    bgColor="#ffffff"
                    fgColor="#0A1628"
                  />
                </button>
              </div>
              <p className="text-[9px] font-mono text-ink-4 text-center mb-3">
                QR is for {selected.token_symbol} on {selected.network} only
              </p>

              {/* Network badges */}
              <div className="flex flex-wrap gap-2 mb-3">
                <span
                  className="font-hud text-[9px] font-bold tracking-[1px] uppercase px-2 py-0.5 rounded-sm"
                  style={{
                    background: "rgba(130,71,229,0.15)",
                    border: "1px solid rgba(130,71,229,0.4)",
                    color: "#A855F7",
                  }}
                >
                  {selected.network}
                </span>
                <span
                  className="font-hud text-[9px] font-bold tracking-[1px] uppercase px-2 py-0.5 rounded-sm"
                  style={{
                    background: "rgba(39,117,202,0.12)",
                    border: "1px solid rgba(39,117,202,0.35)",
                    color: "#60A5FA",
                  }}
                >
                  {selected.token_symbol}
                </span>
                <span className="font-mono text-[9px] text-ink-4 px-2 py-0.5">
                  Min: {minDeposit}
                </span>
              </div>

              {/* Warning */}
              <div
                className="mb-3 p-2.5 rounded-sm text-[9px] font-mono leading-relaxed"
                style={{
                  background: "rgba(245,200,66,0.06)",
                  border: "1px solid rgba(245,200,66,0.2)",
                  color: "#C4A23A",
                }}
              >
                Send only {selected.token_label} on {selected.network}. Wrong token or wrong network may cause permanent loss or manual recovery risk.
              </div>

              {/* Live-mode risk notice */}
              {!paperMode && (
                <div
                  className="mb-3 p-2 rounded-sm text-[9px] font-mono"
                  style={{
                    background: "rgba(255,45,85,0.06)",
                    border: "1px solid rgba(255,45,85,0.2)",
                    color: "#FF6B6B",
                  }}
                >
                  Live mode — real funds. Verify token, network, and address carefully before sending.
                </div>
              )}

              {/* Address + copy */}
              <div
                className="flex items-center gap-2 p-2.5 rounded-sm mb-2"
                style={{
                  background: "rgba(255,255,255,0.04)",
                  border: "1px solid rgba(255,255,255,0.08)",
                }}
              >
                <span
                  className="font-mono text-[10px] text-ink-1 flex-1 tracking-[0.5px] break-all leading-snug"
                  title={selectedAddress}
                >
                  {selectedAddress}
                </span>
                <button
                  type="button"
                  onClick={() => void copyAddress()}
                  className={`flex-shrink-0 py-1.5 px-2.5 font-hud text-[9px] font-bold tracking-[1px] uppercase rounded-sm border transition-colors ${
                    copied
                      ? "text-grn border-grn"
                      : "text-gold border-border-2 hover:border-gold"
                  }`}
                  style={
                    copied
                      ? { background: "rgba(0,255,156,0.15)" }
                      : { background: "rgba(245,200,66,0.10)" }
                  }
                >
                  {copied ? "Copied!" : "Copy"}
                </button>
              </div>

              {balance !== undefined && (
                <p className="text-[9px] font-mono text-ink-4 text-center mt-1.5">
                  Balance: ${balance.toFixed(2)} USDC
                  {paperMode ? " (paper)" : ""}
                </p>
              )}
            </>
          )}
        </div>
      </div>

      {/* Fullscreen QR overlay */}
      {fullscreen && selected && hasAddress && (
        <div
          className="fixed inset-0 z-[60] flex flex-col items-center justify-center"
          style={{ background: "rgba(0,0,0,0.92)" }}
          onClick={() => setFullscreen(false)}
          role="dialog"
          aria-modal="true"
          aria-label={`${selected.display_label} QR Code fullscreen`}
        >
          <div
            className="p-5 bg-white rounded-md"
            onClick={(e) => e.stopPropagation()}
          >
            <QRCodeSVG
              value={selectedAddress}
              size={260}
              level="M"
              bgColor="#ffffff"
              fgColor="#0A1628"
            />
          </div>
          <p className="mt-5 text-[10px] font-mono text-ink-3 pointer-events-none">
            {selected.token_symbol} on {selected.network} · tap anywhere to close
          </p>
        </div>
      )}
    </>
  );
}
