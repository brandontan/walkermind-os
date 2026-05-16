import { useEffect, useState } from "react";
import { makeApi, type WalletInfo } from "../lib/api";
import { useAuth } from "../lib/auth";

export function WalletPage() {
  const { user } = useAuth();
  const api = makeApi(user?.token ?? null);
  const [wallet, setWallet] = useState<WalletInfo | null>(null);
  const [copied, setCopied] = useState(false);

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

  function truncateHash(hash: string): string {
    if (hash.length <= 14) return hash;
    return `${hash.slice(0, 6)}…${hash.slice(-4)}`;
  }

  function formatDate(iso: string): string {
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }

  return (
    <div className="pb-24 px-4 overflow-x-hidden max-w-full">
      <div className="pt-6 pb-4">
        <h1 className="text-xl font-bold text-primary">Wallet</h1>
      </div>

      {/* Balance */}
      <div className="bg-card border border-border rounded-xl p-5 mb-4">
        <p className="text-muted text-xs uppercase tracking-wide mb-1">USDC Balance</p>
        <p className="text-3xl font-bold text-primary">${wallet.balance_usdc.toFixed(2)}</p>
        <p className="text-muted text-xs mt-1">Polygon network</p>
      </div>

      {/* Deposit */}
      <div className="bg-card border border-border rounded-xl p-5 mb-4">
        <p className="text-primary font-medium text-sm mb-3">Deposit Address (Polygon)</p>
        <div className="bg-bg border border-border rounded-lg p-3 font-mono text-xs text-muted break-all mb-3">
          {wallet.deposit_address}
        </div>
        <button
          onClick={copyAddress}
          className="w-full py-2.5 rounded-lg border border-border text-sm font-medium transition-colors hover:border-amber hover:text-amber"
        >
          {copied ? "✓ Copied!" : "Copy Address"}
        </button>
        <p className="text-muted text-xs mt-3 text-center">
          Send USDC only on the Polygon network
        </p>
      </div>

      {/* Transaction history */}
      {wallet.ledger_recent.length > 0 && (
        <div className="bg-card border border-border rounded-xl p-4">
          <p className="text-primary font-medium text-sm mb-3">Recent Transactions</p>
          <div className="space-y-2">
            {wallet.ledger_recent.map((entry, i) => (
              <div key={i} className="flex items-start justify-between gap-2 py-2 border-b border-border/50 last:border-0 min-w-0">
                <div className="min-w-0 flex-1">
                  <p className="text-primary text-sm capitalize truncate">{entry.type.replace("_", " ")}</p>
                  {entry.note && (
                    <p className="font-mono text-xs text-muted truncate">{truncateHash(entry.note)}</p>
                  )}
                </div>
                <div className="flex-shrink-0 text-right">
                  <p className={`text-sm font-medium ${entry.amount_usdc >= 0 ? "text-green" : "text-red"}`}>
                    {entry.amount_usdc >= 0 ? "+" : ""}${Math.abs(entry.amount_usdc).toFixed(2)}
                  </p>
                  <p className="text-muted text-xs">{formatDate(entry.created_at)}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
