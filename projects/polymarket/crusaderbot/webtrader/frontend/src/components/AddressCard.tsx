import { useState } from "react";

type Props = {
  label: string;
  address: string;
};

export function AddressCard({ label, address }: Props) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(address);
      } else {
        // Fallback for non-secure contexts: select and execCommand
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
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      /* Clipboard refused — leave UI unchanged so the user can copy manually. */
    }
  };

  return (
    <div className="mb-3 px-3.5 py-3 bg-surface border border-border-2 clip-card">
      <div className="font-mono text-[9px] tracking-[2px] text-ink-3 mb-1.5 uppercase">
        {label}
      </div>
      <div className="flex items-center gap-2.5">
        <div className="font-mono text-[11px] text-ink-1 break-all flex-1 tracking-[0.5px]">
          {address}
        </div>
        <button
          type="button"
          onClick={handleCopy}
          className={`flex-shrink-0 py-1.5 px-2.5 font-hud text-[9px] font-bold tracking-[1px] uppercase rounded-sm transition-colors border ${
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
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
    </div>
  );
}
