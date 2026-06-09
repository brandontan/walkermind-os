import { useEffect, useRef, useState } from "react";
import { QRCodeSVG } from "qrcode.react";

interface Props {
  address: string;
  paperMode: boolean;
  balance?: number;
  onClose: () => void;
}

export function DepositModal({ address, paperMode, balance, onClose }: Props) {
  const [copied, setCopied] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const copyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (copyTimerRef.current !== null) clearTimeout(copyTimerRef.current);
    };
  }, []);

  const hasAddress = Boolean(address);

  const copyAddress = async () => {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(address);
      } else {
        const ta = document.createElement("textarea");
        ta.value = address;
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
        aria-label="Deposit USDC"
      >
        <div
          className="w-full max-w-sm bg-surface border border-border-1 clip-card p-5 pb-8 md:pb-5 max-h-[90vh] overflow-y-auto"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <div className="flex items-start justify-between mb-4">
            <div>
              <p className="font-hud text-[11px] font-bold tracking-[2px] uppercase text-gold">
                {paperMode ? "Paper Wallet Address" : "Deposit USDC"}
              </p>
              {paperMode ? (
                <p className="text-[9px] font-mono text-ink-3 mt-0.5">
                  Paper Mode — no real funds at risk
                </p>
              ) : (
                <p className="text-[9px] font-mono text-ink-3 mt-0.5">
                  Polygon · USDC only
                </p>
              )}
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

          {!hasAddress ? (
            <div className="py-8 text-center space-y-1.5">
              <p className="text-[10px] font-mono text-ink-3">
                No deposit address available.
              </p>
              <p className="text-[9px] font-mono text-ink-4">
                Set up your wallet via the Telegram bot.
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
                  aria-label="Tap to enlarge QR code"
                  title="Tap to enlarge"
                >
                  <QRCodeSVG
                    value={address}
                    size={156}
                    level="M"
                    bgColor="#ffffff"
                    fgColor="#0A1628"
                  />
                </button>
              </div>
              <p className="text-[9px] font-mono text-ink-4 text-center mb-3">
                Tap QR to enlarge · Scan with any crypto wallet
              </p>

              {/* Network badges */}
              <div className="flex gap-2 mb-3">
                <span
                  className="font-hud text-[9px] font-bold tracking-[1px] uppercase px-2 py-0.5 rounded-sm"
                  style={{
                    background: "rgba(130,71,229,0.15)",
                    border: "1px solid rgba(130,71,229,0.4)",
                    color: "#A855F7",
                  }}
                >
                  Polygon
                </span>
                <span
                  className="font-hud text-[9px] font-bold tracking-[1px] uppercase px-2 py-0.5 rounded-sm"
                  style={{
                    background: "rgba(39,117,202,0.12)",
                    border: "1px solid rgba(39,117,202,0.35)",
                    color: "#60A5FA",
                  }}
                >
                  USDC
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
                Send only USDC on the Polygon network. Other tokens or networks will result in permanent loss.
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
                  Live mode — real funds. Verify the address carefully before sending.
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
                  title={address}
                >
                  {address}
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
      {fullscreen && hasAddress && (
        <div
          className="fixed inset-0 z-[60] flex flex-col items-center justify-center"
          style={{ background: "rgba(0,0,0,0.92)" }}
          onClick={() => setFullscreen(false)}
          role="dialog"
          aria-modal="true"
          aria-label="QR Code fullscreen"
        >
          <div
            className="p-5 bg-white rounded-md"
            onClick={(e) => e.stopPropagation()}
          >
            <QRCodeSVG
              value={address}
              size={260}
              level="M"
              bgColor="#ffffff"
              fgColor="#0A1628"
            />
          </div>
          <p className="mt-5 text-[10px] font-mono text-ink-3 pointer-events-none">
            Tap anywhere to close
          </p>
        </div>
      )}
    </>
  );
}
