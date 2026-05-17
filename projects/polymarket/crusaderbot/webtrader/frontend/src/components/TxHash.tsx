import { useState } from "react";

type Props = {
  hash: string;
  className?: string;
};

function truncateHash(hash: string): string {
  if (hash.length <= 12) return hash;
  return `${hash.slice(0, 6)}...${hash.slice(-4)}`;
}

async function copyToClipboard(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  // Fallback for non-secure contexts
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.focus();
  ta.select();
  // eslint-disable-next-line deprecation/deprecation
  document.execCommand("copy");
  document.body.removeChild(ta);
}

const CopyIcon = ({ copied }: { copied: boolean }) => (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    width="10"
    height="10"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2.5"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden
  >
    {copied ? (
      <polyline points="20 6 9 17 4 12" />
    ) : (
      <>
        <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
        <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
      </>
    )}
  </svg>
);

export function TxHash({ hash, className = "" }: Props) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await copyToClipboard(hash);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      /* clipboard unavailable — hash remains selectable */
    }
  };

  return (
    <span className={`inline-flex items-center gap-1 ${className}`}>
      <span className="font-mono text-ink-1 tracking-[0.5px]">
        {truncateHash(hash)}
      </span>
      <button
        type="button"
        onClick={handleCopy}
        className={`flex-shrink-0 p-0.5 rounded transition-colors ${
          copied ? "text-grn" : "text-ink-3 hover:text-gold"
        }`}
        title={copied ? "Copied!" : "Copy to clipboard"}
        aria-label={copied ? "Copied!" : "Copy hash to clipboard"}
      >
        <CopyIcon copied={copied} />
      </button>
    </span>
  );
}
