import { useEffect, useState } from "react";
import { makeApi, type WalletInfo } from "../lib/api";
import { useAuth } from "../lib/auth";

export function WalletPage() {
  const { user } = useAuth();
  const api = makeApi(user?.token ?? null);
  const [wallet, setWallet] = useState<WalletInfo | null>(null);
  const [copied, setCopied]   = useState(false);

  useEffect(() => {
    api.getWallet().then(setWallet).catch(console.error);
  }, [user?.token]); // eslint-disable-line react-hooks/exhaustive-deps

  async function copyAddress() {
    if (!wallet) return;
    await navigator.clipboard.writeText(wallet.deposit_address);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  if (!wallet) return <div className="p-4 text-muted text-sm">Loading…</div>;

  function truncateHash(note: string): string {
    const suppressed = new Set(["yes", "no", "true", "false"]);
    if (suppressed.has(note.toLowerCase())) return "";
    if (!note.startsWith("0x") || note.length <= 14) return note;
    return `${note.slice(0, 6)}…${note.slice(-4)}`;
  }

  function formatDate(iso: string): string {
    const d = new Date(iso);
    return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  }

  const shortAddr = wallet.deposit_address.length > 12
    ? `${wallet.deposit_address.slice(0, 6)}…${wallet.deposit_address.slice(-4)}`
    : wallet.deposit_address;

  return (
    <div className="pb-28 px-4 overflow-x-hidden max-w-full animate-page-in">
      <div className="pt-6 pb-4">
        <h1 className="text-xl font-bold text-primary">Wallet</h1>
      </div>

      {/* Balance hero — blue gradient */}
      <div
        className="rounded-2xl p-5 mb-4 border border-blue/20"
        style={{ background: "linear-gradient(135deg, rgba(77,158,255,0.12) 0%, rgba(77,158,255,0.04) 100%)" }}
      >
        <p className="text-muted text-xs uppercase tracking-wide mb-1">USDC Balance</p>
        <p className="text-4xl font-bold text-primary font-mono">${wallet.balance_usdc.toFixed(2)}</p>
        <p className="text-muted text-xs mt-1">Polygon network</p>
      </div>

      {/* Deposit address */}
      <div className="bg-card border border-border rounded-2xl p-5 mb-4">
        <p className="text-primary font-semibold text-sm mb-3">Deposit Address (Polygon)</p>
        <div className="bg-bg border border-border rounded-xl p-3 font-mono text-xs text-muted break-all mb-3">
          {wallet.deposit_address}
        </div>
        <button
          onClick={copyAddress}
          className={`w-full py-2.5 rounded-button text-sm font-semibold transition-all ${
            copied
              ? "bg-green/10 border border-green/30 text-green"
              : "border border-border text-muted hover:border-gold hover:text-gold"
          }`}
        >
          {copied ? "✓ Copied!" : "Copy Address"}
        </button>
        <p className="text-muted text-xs mt-3 text-center">
          Send USDC only on the Polygon network
        </p>
      </div>

      {/* Transaction history */}
      {wallet.ledger_recent.length > 0 && (
        <div className="bg-card border border-border rounded-2xl overflow-hidden">
          <p className="text-primary font-semibold text-sm px-4 pt-4 pb-2">Recent Transactions</p>
          <div className="divide-y divide-border">
            {wallet.ledger_recent.map((entry, i) => {
              const noteDisplay = entry.note ? truncateHash(entry.note) : "";
              return (
                <div key={i} className="flex items-center justify-between gap-3 px-4 py-3">
                  <div className="min-w-0 flex-1">
                    <p className="text-primary text-sm capitalize truncate">{entry.type.replace("_", " ")}</p>
                    <p className="font-mono text-xs text-muted truncate">
                      Paper · {noteDisplay || shortAddr}
                    </p>
                  </div>
                  <div className="shrink-0 text-right">
                    <p className={`text-sm font-semibold font-mono ${entry.amount_usdc >= 0 ? "text-green" : "text-red"}`}>
                      {entry.amount_usdc >= 0 ? "+" : ""}${Math.abs(entry.amount_usdc).toFixed(2)}
                    </p>
                    <p className="text-muted text-xs">{formatDate(entry.created_at)}</p>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
