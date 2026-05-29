import { useCallback, useEffect, useMemo, useState } from "react";
import { DesktopPageHeader } from "../components/DesktopPageHeader";
import { Toggle } from "../components/Toggle";
import { TopBar } from "../components/TopBar";
import {
  makeApi,
  type AdminOverview,
  type AdminStrategy,
  type AdminUser,
} from "../lib/api";
import { useAuth } from "../lib/auth";

function fmtUsd(v: number | null | undefined): string {
  if (v == null) return "—";
  return `$${v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function AdminPage() {
  const { user } = useAuth();
  const api = useMemo(() => makeApi(user?.token ?? null), [user?.token]);

  const [allowed, setAllowed] = useState<boolean | null>(null);
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [strategies, setStrategies] = useState<AdminStrategy[]>([]);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [savingStrat, setSavingStrat] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const me = await api.getMe();
      if (!me.is_admin) { setAllowed(false); return; }
      setAllowed(true);
      const [ov, st, us] = await Promise.all([
        api.getAdminOverview(),
        api.getAdminStrategies(),
        api.getAdminUsers(100, 0),
      ]);
      setOverview(ov);
      setStrategies(st.strategies);
      setUsers(us.users);
      setError(null);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (msg.includes("403")) { setAllowed(false); return; }
      setError(msg.replace(/^\d+:\s*/, ""));
    }
  }, [api]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    const id = setInterval(() => { if (allowed) void load(); }, 30_000);
    return () => clearInterval(id);
  }, [load, allowed]);

  async function handleToggle(name: string, next: boolean) {
    setSavingStrat(name);
    setStrategies((prev) => prev.map((s) => s.name === name ? { ...s, enabled: next } : s));
    try {
      await api.toggleStrategy(name, next);
    } catch (e) {
      // revert on failure
      setStrategies((prev) => prev.map((s) => s.name === name ? { ...s, enabled: !next } : s));
      console.error("toggle strategy failed", e);
    } finally {
      setSavingStrat(null);
    }
  }

  if (allowed === false) return (
    <>
      <TopBar />
      <div className="p-6 text-center text-ink-3 font-mono text-sm">
        🔒 Admin only. Your account doesn’t have operator access.
      </div>
    </>
  );

  if (allowed === null || (!overview && !error)) return (
    <>
      <TopBar />
      <div className="p-4 text-ink-3 text-sm font-mono">Loading admin console…</div>
    </>
  );

  const g = overview?.guards ?? {};
  const allGuardsOpen = Object.values(g).length > 0 && Object.entries(g)
    .filter(([k]) => k !== "USE_REAL_CLOB")
    .every(([, v]) => v);

  return (
    <>
      <TopBar />
      <div className="px-3.5 pt-3.5 pb-6 animate-page-in">
        <DesktopPageHeader
          title={<>OPS <span className="text-gold">CONSOLE</span></>}
          subtitle="OVERVIEW · STRATEGIES · USERS"
        />
        {error && <p className="text-red text-[12px] font-mono mb-3">{error}</p>}

        {/* ── Master pool (funding target) ── */}
        {overview && (
          <Section title="Master Hot-Pool (fund this for go-live)">
            <div className="space-y-2">
              <Field label="Address">
                {overview.pool.address ? (
                  <button
                    type="button"
                    onClick={() => navigator.clipboard?.writeText(overview.pool.address ?? "")}
                    className="font-mono text-[11px] text-gold break-all text-left hover:underline"
                    title="Tap to copy"
                  >
                    {overview.pool.address} ⧉
                  </button>
                ) : <span className="text-ink-3 font-mono text-[11px]">unavailable</span>}
              </Field>
              <div className="grid grid-cols-2 gap-2">
                <Stat label="USDC" value={fmtUsd(overview.pool.usdc)} />
                <Stat label="MATIC (gas)" value={overview.pool.matic == null ? "—" : overview.pool.matic.toFixed(4)} />
              </div>
            </div>
          </Section>
        )}

        {/* ── Live readiness / guards ── */}
        {overview && (
          <Section title="Live Activation Guards">
            <div className="grid grid-cols-2 gap-1.5">
              {Object.entries(overview.guards).map(([k, v]) => (
                <div key={k} className="flex items-center gap-1.5">
                  <span style={{ color: v ? "#00FF9C" : "#FF6B6B" }} className="font-mono text-[11px]">
                    {v ? "✓" : "✕"}
                  </span>
                  <span className="font-mono text-[9px] text-ink-2">{k}</span>
                </div>
              ))}
            </div>
            <p className="text-[10px] font-mono mt-2" style={{ color: allGuardsOpen ? "#00FF9C" : "#F5C842" }}>
              {allGuardsOpen ? "LIVE OPEN system-wide" : "LIVE LOCKED — guards off (PAPER)"}
              {overview.kill_switch_active ? " · ⛔ KILL SWITCH ACTIVE" : ""}
            </p>
          </Section>
        )}

        {/* ── Counts ── */}
        {overview && (
          <Section title="System">
            <div className="grid grid-cols-2 gap-2">
              <Stat label="Users" value={String(overview.counts.users)} />
              <Stat label="Auto-trade ON" value={String(overview.counts.auto_trade_on)} />
              <Stat label="Live users" value={String(overview.counts.live_users)} />
              <Stat label="Admins" value={String(overview.counts.admins)} />
              <Stat label="Open (paper)" value={String(overview.counts.open_positions_paper)} />
              <Stat label="Open (live)" value={String(overview.counts.open_positions_live)} />
              <Stat label="Wallets USDC" value={fmtUsd(overview.counts.total_wallet_usdc)} />
            </div>
          </Section>
        )}

        {/* ── Strategies on/off ── */}
        <Section title="Strategies (global on/off)">
          <div className="space-y-1">
            {strategies.map((s) => (
              <div key={s.name} className="flex items-center justify-between py-1.5 border-b border-surface-3 last:border-0">
                <div>
                  <span className="font-mono text-[12px] text-ink-1">{s.name}</span>
                  <span className="ml-2 font-mono text-[9px]" style={{ color: s.enabled ? "#00FF9C" : "#888" }}>
                    {s.enabled ? "ON" : "OFF"}
                  </span>
                </div>
                <Toggle
                  checked={s.enabled}
                  onChange={(next) => void handleToggle(s.name, next)}
                  ariaLabel={`Toggle ${s.name}`}
                  disabled={savingStrat === s.name}
                />
              </div>
            ))}
          </div>
          <p className="text-[9px] font-mono text-ink-4 mt-2">
            OFF stops new signals from that strategy for everyone (takes effect next scan tick). Open positions are unaffected.
          </p>
        </Section>

        {/* ── Users ── */}
        <Section title={`Users (${overview?.counts.users ?? users.length})`}>
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="font-hud text-[8px] tracking-[1px] uppercase text-ink-4">
                  <th className="py-1 pr-2">User</th>
                  <th className="py-1 pr-2">Mode</th>
                  <th className="py-1 pr-2 text-right">Balance</th>
                  <th className="py-1 pr-2 text-center">Auto</th>
                  <th className="py-1 text-right">Open</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.user_id} className="border-t border-surface-3">
                    <td className="py-1.5 pr-2">
                      <div className="font-mono text-[11px] text-ink-1">
                        {u.username ? `@${u.username}` : (u.email ?? u.user_id.slice(0, 8))}
                        {u.role === "admin" && <span className="ml-1 text-gold text-[8px]">ADMIN</span>}
                      </div>
                      {u.active_preset && <div className="font-mono text-[8px] text-ink-4">{u.active_preset}</div>}
                    </td>
                    <td className="py-1.5 pr-2">
                      <span className="font-mono text-[9px]" style={{ color: u.trading_mode === "live" ? "#00FF9C" : "#F5C842" }}>
                        {u.trading_mode.toUpperCase()}
                      </span>
                    </td>
                    <td className="py-1.5 pr-2 text-right font-mono text-[11px] text-ink-2">{fmtUsd(u.balance_usdc)}</td>
                    <td className="py-1.5 pr-2 text-center font-mono text-[11px]">
                      {u.paused ? <span style={{ color: "#FF6B6B" }}>paused</span>
                        : u.auto_trade_on ? <span style={{ color: "#00FF9C" }}>on</span>
                        : <span className="text-ink-4">off</span>}
                    </td>
                    <td className="py-1.5 text-right font-mono text-[11px] text-ink-2">{u.open_positions}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      </div>
    </>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-surface border border-border-1 clip-card p-3.5 mb-3">
      <p className="font-hud text-[10px] font-bold tracking-[1.5px] uppercase text-gold mb-2.5">{title}</p>
      {children}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="font-hud text-[8px] tracking-[1.5px] uppercase text-ink-4 mb-0.5">{label}</p>
      {children}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-surface-2 border border-surface-3 rounded-sm px-2.5 py-1.5">
      <p className="font-hud text-[8px] tracking-[1px] uppercase text-ink-4">{label}</p>
      <p className="font-mono text-[13px] text-ink-1 mt-0.5">{value}</p>
    </div>
  );
}
