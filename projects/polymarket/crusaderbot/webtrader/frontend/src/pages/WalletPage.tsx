import { useCallback, useEffect, useMemo, useState } from "react";
import { AddressCard } from "../components/AddressCard";
import { AdvancedOnly } from "../components/AdvancedGate";
import { EmptyState } from "../components/EmptyState";
import { PositionCard } from "../components/PositionCard";
import { TopBar } from "../components/TopBar";
import { WalletCard } from "../components/WalletCard";
import { makeApi, type LedgerEntry, type WalletInfo } from "../lib/api";
import { useAuth } from "../lib/auth";

export function WalletPage() {
  const { user } = useAuth();
  const api = useMemo(() => makeApi(user?.token ?? null), [user?.token]);
  const [info, setInfo] = useState<WalletInfo | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setInfo(await api.getWallet());
    } catch (e) {
      setError(String(e));
    }
  }, [api]);

  useEffect(() => { void load(); }, [load]);

  if (error) return (
    <>
      <TopBar />
      <div className="p-4 text-red text-sm">{error}</div>
    </>
  );
  if (!info) return (
    <>
      <TopBar />
      <div className="p-4 text-ink-3 text-sm font-mono">Loading…</div>
    </>
  );

  const balanceStr = info.balance_usdc.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

  // Essential view shows only the most recent entry; advanced shows full ledger.
  const essentialLedger = info.ledger_recent.slice(0, 1);
  const advancedLedger = info.ledger_recent.slice(1);

  return (
    <>
      <TopBar />
      <div className="px-3.5 pt-3.5 pb-6 animate-page-in">
        <WalletCard
          label="Paper Balance"
          balance={balanceStr}
          mode="Paper Mode · No real funds at risk"
        />

        <AddressCard
          label="Deposit Address · Polygon USDC"
          address={info.deposit_address}
        />

        <div className="flex items-center justify-between mt-3.5 mb-2 mx-0.5">
          <div className="font-hud text-[10px] font-bold tracking-[3px] text-ink-2 uppercase flex items-center gap-2">
            <span className="w-3 h-px bg-gold" aria-hidden />
            Recent Activity
          </div>
        </div>

        {info.ledger_recent.length === 0 ? (
          <EmptyState
            icon="📥"
            title="No Activity Yet"
            text="Credits and debits will appear here once trading starts."
          />
        ) : (
          <>
            {essentialLedger.map((entry, i) => (
              <LedgerCard key={i} entry={entry} />
            ))}
            <AdvancedOnly>
              {advancedLedger.map((entry, i) => (
                <LedgerCard key={`adv-${i}`} entry={entry} />
              ))}
            </AdvancedOnly>
          </>
        )}
      </div>
    </>
  );
}

function LedgerCard({ entry }: { entry: LedgerEntry }) {
  const isCredit = entry.amount_usdc >= 0;
  const tone: "up" | "dn" = isCredit ? "up" : "dn";
  const sign = isCredit ? "+" : "−";
  return (
    <PositionCard
      market={entry.note ?? entry.type}
      positionValue={{ value: `${sign}$${Math.abs(entry.amount_usdc).toFixed(2)}`, tone }}
      side={isCredit ? "credit" : "debit"}
      meta={[
        <>USDC</>,
        <>{formatDate(entry.created_at)}</>,
      ]}
    />
  );
}

function formatDate(ts: string): string {
  try {
    return new Date(ts).toLocaleDateString([], { month: "short", day: "numeric" });
  } catch {
    return ts.slice(0, 10);
  }
}
