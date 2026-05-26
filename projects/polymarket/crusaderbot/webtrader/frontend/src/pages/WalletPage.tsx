import { useCallback, useEffect, useMemo, useState } from "react";
import { AddressCard } from "../components/AddressCard";
import { CollapsibleSection } from "../components/CollapsibleSection";
import { DepositModal } from "../components/DepositModal";
import { DesktopPageHeader } from "../components/DesktopPageHeader";
import { EmptyState } from "../components/EmptyState";
import { PositionCard } from "../components/PositionCard";
import { TopBar } from "../components/TopBar";
import { WalletCard } from "../components/WalletCard";
import { WithdrawModal } from "../components/WithdrawModal";
import { makeApi, type LedgerEntry, type WalletInfo } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useSSE } from "../lib/sse";

export function WalletPage() {
  const { user } = useAuth();
  const api = useMemo(() => makeApi(user?.token ?? null), [user?.token]);
  const [info, setInfo] = useState<WalletInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showDeposit, setShowDeposit] = useState(false);
  const [showWithdraw, setShowWithdraw] = useState(false);
  const [ledgerAll, setLedgerAll] = useState<LedgerEntry[]>([]);
  const [ledgerOffset, setLedgerOffset] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);

  const load = useCallback(async () => {
    try {
      const w = await api.getWallet();
      setInfo(w);
      setLedgerAll(w.ledger_recent);
      setLedgerOffset(w.ledger_recent.length);
      setHasMore(w.ledger_recent.length >= 20);
    } catch (e) {
      setError(String(e));
    }
  }, [api]);

  useEffect(() => { void load(); }, [load]);

  // SSE: refresh balance + ledger when trades open/close or balance changes.
  useSSE(user?.token ?? null, {
    position_opened:  load,
    position_closed:  load,
    portfolio_update: load,
  });

  // 30s polling fallback for SSE stalls.
  useEffect(() => {
    const id = setInterval(load, 30_000);
    return () => clearInterval(id);
  }, [load]);

  const loadMore = useCallback(async () => {
    setLoadingMore(true);
    try {
      const page = await api.getLedger(ledgerOffset);
      // Advance server offset by what the server returned (before client-side dedup),
      // so subsequent requests always fetch the next page even if all entries were dupes.
      setLedgerOffset((prev) => prev + page.entries.length);
      setLedgerAll((prev) => {
        const existingIds = new Set(prev.map((e) => e.id));
        const fresh = page.entries.filter((e) => !existingIds.has(e.id));
        return [...prev, ...fresh];
      });
      setHasMore(page.has_more);
    } catch {
      // Leave hasMore unchanged so the button stays and the user can retry
    } finally {
      setLoadingMore(false);
    }
  }, [api, ledgerOffset]);

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

  const paperMode = info.paper_mode !== false;
  const balanceStr = info.balance_usdc.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

  return (
    <>
      <TopBar />
      <div className="px-3.5 pt-3.5 pb-6 animate-page-in">
        <DesktopPageHeader
          title={<>WAL<span className="text-gold">LET</span></>}
          subtitle="BALANCE · DEPOSITS · LEDGER"
        />
        <div className="md:grid md:grid-cols-2 md:gap-4">
          <div>
            <WalletCard
              label={paperMode ? "Paper Balance" : "Wallet Balance"}
              balance={balanceStr}
              mode={paperMode ? "Paper Mode · No real funds at risk" : "Live Mode · Polygon USDC"}
            />

            {/* Deposit / Withdraw action row */}
            <div className="flex gap-2 mb-3">
              <button
                type="button"
                onClick={() => setShowDeposit(true)}
                className="flex-1 clip-btn font-hud text-[10px] font-bold tracking-[1.5px] uppercase py-2.5 transition-colors"
                style={{
                  background: "rgba(0,255,156,0.08)",
                  border: "1px solid rgba(0,255,156,0.3)",
                  color: "#00FF9C",
                }}
              >
                ↓ Deposit
              </button>
              <button
                type="button"
                onClick={() => setShowWithdraw(true)}
                className="flex-1 clip-btn font-hud text-[10px] font-bold tracking-[1.5px] uppercase py-2.5 transition-colors"
                style={{
                  background: "rgba(245,200,66,0.06)",
                  border: `1px solid rgba(245,200,66,${paperMode ? "0.15" : "0.3"})`,
                  color: `rgba(245,200,66,${paperMode ? "0.45" : "1"})`,
                }}
                title={paperMode ? "Withdraw unavailable in Paper Mode" : undefined}
              >
                ↑ Withdraw
              </button>
            </div>

            <AddressCard
              label="Deposit Address · Polygon USDC"
              address={info.deposit_address}
            />
          </div>

          <div>
            <CollapsibleSection id="wallet_recent_activity" label="Recent Activity">
              {ledgerAll.length === 0 ? (
                <EmptyState
                  icon="📥"
                  title="No Activity Yet"
                  text="Credits and debits will appear here once trading starts."
                />
              ) : (
                <>
                  {ledgerAll.map((entry) => (
                    <LedgerCard key={entry.id} entry={entry} />
                  ))}
                  {hasMore && (
                    <button
                      type="button"
                      onClick={() => void loadMore()}
                      disabled={loadingMore}
                      className="w-full mt-2 py-2 font-hud text-[9px] font-bold tracking-[1.5px] uppercase text-ink-3 border border-border-1 clip-btn transition-colors hover:border-border-2 disabled:opacity-50"
                      style={{ background: "rgba(255,255,255,0.02)" }}
                    >
                      {loadingMore ? "Loading…" : "Load more"}
                    </button>
                  )}
                </>
              )}
            </CollapsibleSection>
          </div>
        </div>
      </div>

      {showDeposit && (
        <DepositModal
          address={info.deposit_address}
          paperMode={paperMode}
          balance={info.balance_usdc}
          onClose={() => setShowDeposit(false)}
        />
      )}

      {showWithdraw && (
        <WithdrawModal
          paperMode={paperMode}
          balance={info.balance_usdc}
          onClose={() => setShowWithdraw(false)}
          onWithdraw={api.requestWithdrawal}
          onSuccess={() => { setShowWithdraw(false); void load(); }}
        />
      )}
    </>
  );
}

/** Replace any bare 0x hex address in a ledger note with a short form. */
function formatNote(note: string): string {
  return note.replace(/(0x[0-9a-fA-F]{8})[0-9a-fA-F]+([0-9a-fA-F]{4})/g, "$1…$2");
}

function LedgerCard({ entry }: { entry: LedgerEntry }) {
  const isCredit = entry.amount_usdc >= 0;
  const tone: "up" | "dn" = isCredit ? "up" : "dn";
  const sign = isCredit ? "+" : "−";
  const label = entry.note ? formatNote(entry.note) : entry.type;
  return (
    <PositionCard
      market={label}
      positionValue={
        Math.abs(entry.amount_usdc) < 0.005
          ? { value: "$0.00", tone: "zero" }
          : { value: `${sign}$${Math.abs(entry.amount_usdc).toFixed(2)}`, tone }
      }
      side={isCredit ? "credit" : "debit"}
      meta={[<>USDC</>, <>{formatDate(entry.created_at)}</>]}
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
